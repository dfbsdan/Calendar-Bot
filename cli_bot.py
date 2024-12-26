from openai import OpenAI
from openai.types.chat import ChatCompletion

import json

from utils import OPENAI_API_KEY, ASSISTANT_PROMPT, ASSISTANT_TOOLS_CLI, FIRST_UTTERANCE, create_event


openai_client = OpenAI(api_key=OPENAI_API_KEY)

# TODO: Check for availability

def parse_response(response: ChatCompletion):
    choice = response.choices[0]
    if choice.finish_reason == 'tool_calls': # finished
        tool_calls = choice.message.tool_calls
        assert isinstance(tool_calls, list) and len(tool_calls) > 0
        arguments = json.loads(tool_calls[0].function.arguments)
        assert isinstance(arguments, dict)
        return arguments
    message = choice.message.content
    assert isinstance(message, str)
    return message

def get_response(utterances: list[str]):
    assert len(utterances) > 0
    assistant_role = {"role": "developer", "content": ASSISTANT_PROMPT}
    utterances = [
        {
            "role": "assistant" if i % 2 == 0 else "user", 
            "content": utt,
        } 
        for i, utt in enumerate(utterances)
    ]
    messages = [assistant_role, *utterances]
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=ASSISTANT_TOOLS_CLI,
    )
    return parse_response(response)

if __name__ == '__main__':
    assistant_prefix = '> ASSISTANT: '
    user_prefix = '> '
    print(assistant_prefix + FIRST_UTTERANCE)
    user_utt = input(user_prefix)
    utterances = [FIRST_UTTERANCE, user_utt]
    while True:
        bot_response = get_response(utterances)
        if isinstance(bot_response, dict): # finished
            success, msg = create_event(**bot_response)
            print(assistant_prefix + msg)
            break
        assert isinstance(bot_response, str)
        print(assistant_prefix + bot_response)
        user_utt = input(user_prefix)
        utterances += [bot_response, user_utt]
