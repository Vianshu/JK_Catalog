import json
path = r'C:\Users\HP\.gemini\antigravity-ide\brain\85960a6e-c847-4619-881f-365881ba39eb\.system_generated\logs\transcript_full.jsonl'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
    for i in [94, 95, 430, 619]:
        data = json.loads(lines[i])
        if 'content' in data and data['content']:
            print(f'Line {i} content length: {len(data["content"])}')
            with open(f'match_{i}.txt', 'w', encoding='utf-8') as out:
                out.write(data['content'])
        elif 'tool_calls' in data:
            print(f'Line {i} has tool calls.')
            for call in data['tool_calls']:
                with open(f'match_{i}.txt', 'a', encoding='utf-8') as out:
                    out.write(json.dumps(call, indent=2))
