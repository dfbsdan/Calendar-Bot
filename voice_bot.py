from flask import Flask, render_template
from flask_socketio import SocketIO

from websocket import WebSocket

from pydub import AudioSegment

import json
import base64
from io import BytesIO

from utils import OPENAI_API_KEY, ASSISTANT_PROMPT, ASSISTANT_TOOLS_VOICE, FIRST_UTTERANCE, create_event


OPENAI_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17"
OPENAI_HEADERS = [
    "Authorization: Bearer " + OPENAI_API_KEY,
    "OpenAI-Beta: realtime=v1"
]
OPENAI_SOCKET_TIMEOUT = 2 * 60

app = Flask(__name__)
socketio = SocketIO(app)

def setup_openai_socket():
    ws = WebSocket()
    # Connect
    ws.connect(OPENAI_URL, header=OPENAI_HEADERS, timeout=OPENAI_SOCKET_TIMEOUT)
    event: dict = json.loads(ws.recv())
    assert event["type"] == "session.created", f"Unexpected event: {json.dumps(event, indent=2)}"
    # Session configuration
    event = {
        "type": "session.update",
        "session": {
            "modalities": ["audio", "text"],
            "model": "gpt-4o-realtime-preview-2024-12-17",
            "instructions": ASSISTANT_PROMPT,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "turn_detection": None, # { # TODO: VAD
            #     "type": "server_vad",
            #     "create_response": False,
            # },
            "tools": ASSISTANT_TOOLS_VOICE, 
            "tool_choice": "auto",
        }
    }
    ws.send(json.dumps(event))
    event: dict = json.loads(ws.recv())
    assert event["type"] == "session.updated", f"Unexpected event: {json.dumps(event, indent=2)}"
    # Send first utterance
    event = {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": FIRST_UTTERANCE,
                }
            ]
        }
    }
    ws.send(json.dumps(event))
    event: dict = json.loads(ws.recv())
    assert event["type"] == "conversation.item.created", f"Unexpected event: {json.dumps(event, indent=2)}"
    return ws

ws = setup_openai_socket()

def preprocess_input_audio(audio_bytes: bytes):
    audio: AudioSegment = AudioSegment.from_file(BytesIO(audio_bytes), format="webm")
    pcm_data = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2).raw_data
    return base64.b64encode(pcm_data).decode('ascii')

def get_response():
    # Commit audio
    ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
    event: dict = json.loads(ws.recv())
    assert event["type"] == "input_audio_buffer.committed", f"Unexpected event: {json.dumps(event, indent=2)}"
    # Create response
    ws.send(json.dumps({"type": "response.create"}))
    event: dict = json.loads(ws.recv())
    assert event["type"] == "conversation.item.created", f"Unexpected event: {json.dumps(event, indent=2)}"
    event: dict = json.loads(ws.recv())
    assert event["type"] == "response.created", f"Unexpected event: {json.dumps(event, indent=2)}"
    # Receive and transmit model outputs
    done = audio_received = False
    while not done:
        event: dict = json.loads(ws.recv())
        match event["type"]:
            case 'response.audio.delta':
                audio_received = True
                chunk = base64.b64decode(event['delta'])
                socketio.emit('response_audio', {'audio': chunk})
            case 'response.audio_transcript.delta' | 'response.text.delta':
                chunk = event['delta']
                socketio.emit('response_transcript', {'text': chunk})
            case 'response.done':
                socketio.emit('stop_response')
                done = True
                if event["response"]["output"][0]["type"] == 'function_call':
                    arguments = json.loads(event["response"]["output"][0]["arguments"])
                    assert isinstance(arguments, dict)
                    success, msg = create_event(**arguments)
                    socketio.emit('response_transcript', {'text': msg})
            # case 'input_audio_buffer.speech_stopped': # TODO: VAD Support
            #     print("Audio buffer stopped by VAD.")
            #     print("FRONTEND: SENDING: stop_recording")
            #     socketio.emit('stop_recording')
            #     # TODO: Commit and/or clear buffer (necessary?)
            #     print("OPENAI: SENDING: response.create")
            #     ws.send(json.dumps({"type": "response.create"}))
            case _:
                print(f"OPENAI: RECEIVED: {event['type']}")
    # Clear buffer
    ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
    event: dict = json.loads(ws.recv())
    assert event["type"] == "input_audio_buffer.cleared", f"Unexpected event: {json.dumps(event, indent=2)}"
    print(f"FINISHED GENERATING RESPONSE (audio received: {audio_received})")

@app.route("/")
def index():
    return render_template("index.html", context={'message': FIRST_UTTERANCE})

@socketio.on("input_audio")
def handle_audio(data):
    audio_bytes = preprocess_input_audio(data['audio'])
    # Send chunks
    chunk_size = 4096
    for i in range(0, len(audio_bytes), chunk_size):
        chunk = audio_bytes[i:i + chunk_size]
        event = {
            "type": "input_audio_buffer.append",
            "audio": chunk,
        }
        ws.send(json.dumps(event)) # no response event expected
    get_response()

# @socketio.on("stop_recording")
# def stop_recording():
#     print("Recording stopped.")
#     print("OPENAI: SENDING: input_audio_buffer.commit")
#     ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

if __name__ == '__main__':
    socketio.run(app)
