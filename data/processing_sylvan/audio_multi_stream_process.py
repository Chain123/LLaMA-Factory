import os
import re
import json
import csv
import argparse
from typing import List, Dict, Tuple, Optional
from pydub import AudioSegment

# 解析一行文本 [start,end]\tSpeakerID\tGender\tText
LINE_PATTERN = re.compile(
    r'^\s*\[\s*(?P<start>[-+]?\d+(\.\d+)?)\s*,\s*(?P<end>[-+]?\d+(\.\d+)?)\s*\]\s*'
    r'\t\s*(?P<spk_id>[^\t]+)\s*\t\s*(?P<gender>[^\t]+)\s*\t\s*(?P<text>.*)\s*$'
)

def parse_transcript_file(path: str) -> List[Dict]:
    segments = []
    with open(path, 'r', encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                # 空行直接跳过
                continue
            m = LINE_PATTERN.match(line)
            if not m:
                # 格式不匹配的行跳过（也可改为 raise）
                continue
            start = float(m.group('start'))
            end = float(m.group('end'))
            if end < start:
                # 不合理片段跳过
                continue

            spk_id = m.group('spk_id').strip()
            gender = m.group('gender').strip()
            text = m.group('text').strip()

            # 新增：过滤空数据行（说话人ID为 0 且 性别为 none）
            if spk_id == '0' and gender.lower() == 'none':
                continue

            # 如需更严格，也可以同时过滤没有文本的行（可选）
            # if (spk_id == '0' and gender.lower() == 'none') or text == '':
            #     continue

            seg = {
                'start': start,
                'end': end,
                'spk_id': spk_id,
                'gender': gender,
                'text': text,
            }
            segments.append(seg)
    return segments

def load_audio(audio_path: str) -> AudioSegment:
    # pydub 会根据后缀选择编码器，需要 ffmpeg 支持
    return AudioSegment.from_file(audio_path)

def cut_audio_segments(audio_path: str, segments: List[Dict], out_dir: str,
                       dialog_id: str, speaker_label: str,
                       export_format: Optional[str] = None) -> List[Dict]:
    """
    根据 segments 切分音频，并导出到 out_dir/dialog_id/<speaker_label>/seg_xxx.ext。
    返回带有文件路径的分段字典列表（包含 start, end, spk_id, gender, audio_path）。
    export_format 可指定导出格式，如 'wav' 或 'mp3'，默认沿用源文件后缀。
    """
    os.makedirs(os.path.join(out_dir, dialog_id, speaker_label), exist_ok=True)
    audio = load_audio(audio_path)
    src_ext = os.path.splitext(audio_path)[1].lower().lstrip('.')
    out_ext = export_format if export_format else (src_ext if src_ext else 'wav')

    results = []
    for idx, seg in enumerate(segments):
        ms_start = int(seg['start'] * 1000)
        ms_end = int(seg['end'] * 1000)
        ms_start = max(0, ms_start)
        ms_end = min(len(audio), ms_end)
        if ms_end <= ms_start:
            continue
        chunk = audio[ms_start:ms_end]
        out_name = f"seg_{idx:04d}_{seg['start']:.3f}-{seg['end']:.3f}.{out_ext}"
        out_path = os.path.join(out_dir, dialog_id, speaker_label, out_name)
        chunk.export(out_path, format=out_ext)

        res = dict(seg)
        abs_path = os.path.abspath(out_path)
        res['audio_path'] = abs_path
        # relative to out_dir, so audios are portable
        res['rel_audio_path'] = os.path.relpath(abs_path, start=out_dir)
        results.append(res)
    return results

def guess_dialog_id_from_pair(audio_a: str, audio_b: str) -> str:
    """
    根据两个音频文件名推测一个对话ID。你可以按需修改此逻辑。
    这里取两者的最长公共前缀（去除扩展名），再清理尾部非字母数字的分隔符。
    """
    base_a = os.path.splitext(os.path.basename(audio_a))[0]
    base_b = os.path.splitext(os.path.basename(audio_b))[0]
    # 寻找最长公共前缀
    i = 0
    for x, y in zip(base_a, base_b):
        if x == y:
            i += 1
        else:
            break
    common = base_a[:i]
    common = common.rstrip('_- .')
    if not common:
        # 如果没有公共前缀，使用组合名
        common = f"{base_a}__{base_b}"
    return common

def merge_turns_by_time(segs_a: List[Dict], segs_b: List[Dict], role_a: str = 'user', role_b: str = 'assistant') -> Tuple[List[Dict], List[str]]:
    """
    按 start 时间排序合并两个说话人的分段。若时间重叠则按 start 排序。
    输出每个 turn 的结构：
    {
      'from': 'human' 或 'assistant',
      'value': 'file:///absolute/path',
      'meta': { 'spk_id': ..., 'gender': ..., 'start': ..., 'end': ... }
    }
    """
    # 排序
    a_sorted = sorted(segs_a, key=lambda s: (s['start'], s['end']))
    b_sorted = sorted(segs_b, key=lambda s: (s['start'], s['end']))
    # 将第一位说话人映射为 human，第二位为 assistant
    # turns = []
    # for seg, role in [(x, 'human') for x in a_sorted] + [(y, 'assistant') for y in b_sorted]:
    #     turns.append({
    #         'from': role,
    #         'value': f"file:///{seg['audio_path'].replace(os.sep, '/')}",
    #         'meta': {
    #             'spk_id': seg.get('spk_id'),
    #             'gender': seg.get('gender'),
    #             'start': seg.get('start'),
    #             'end': seg.get('end'),
    #         }
    #     })
    # # 再按时间排序整合（确保 human/assistant 交替随时间推进）
    # turns = sorted(turns, key=lambda t: (t['meta']['start'], t['meta']['end']))
    # return turns
    # mixed = []
    # for seg in a_sorted:
    #     mixed.append((seg, role_a))
    # for seg in b_sorted:
    #     mixed.append((seg, role_b))
    # mixed.sort(key=lambda t: (t[0]['start'], t[0]['end']))

    # messages: List[Dict] = []
    # audios: List[str] = []

    # for seg, role in mixed:
    #     txt = (seg.get('text') or "").strip()
    #     if role == 'user':
    #         # 仅音频占位符
    #         messages.append({'role': 'user', 'content': '<audio>'})
    #         rel = seg.get('rel_audio_path') or seg.get('audio_path') or ''
    #         audios.append(rel.replace(os.sep, '/'))
    #     else:
    #         # 仅文本；若无文本则跳过该条（可按需改为保留空字符串）
    #         if txt:
    #             messages.append({'role': 'assistant', 'content': txt})

    # return messages, audios
    mixed = []
    for seg in a_sorted:
        mixed.append((seg, role_a))
    for seg in b_sorted:
        mixed.append((seg, role_b))
    mixed.sort(key=lambda t: (t[0]['start'], t[0]['end']))

    messages: List[Dict] = []
    audios: List[str] = []

    for seg, role in mixed:
        txt = (seg.get('text') or "").strip()
        if role == 'user':
            messages.append({'role': 'user', 'content': '<audio>'})
            # 使用绝对路径（cut_audio_segments 已设 audio_path 为绝对路径）
            abs_path = seg.get('audio_path') or ''
            audios.append(abs_path.replace(os.sep, '/'))
        else:
            if txt:
                messages.append({'role': 'assistant', 'content': txt})

    return messages, audios

def build_target_dialog(messages: List[Dict], audios: List[str]) -> Dict: 
    return { 'messages': messages, 'audios': audios }


def build_sharegpt_dialog(dialog_id: str, turns: List[Dict]) -> Dict:
    return {
        'id': dialog_id,
        'conversations': [{'from': t['from'], 'value': t['value']} for t in turns],
        # 如需保留更多元数据，可另存一个字段：
        'meta': {'turns': turns}  # 可选；有些工具不需要这个
    }

def read_manifest(manifest_path: str) -> List[Dict]:
    """
    读取 CSV 清单，列应包含：
    dialog_id,audio_a,audio_b,text_a,text_b
    """
    pairs = []
    with open(manifest_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            required = ['dialog_id', 'audio_a', 'audio_b', 'text_a', 'text_b']
            if not all(k in row and row[k] for k in required):
                raise ValueError(f"Manifest row missing fields: {row}")
            pairs.append({
                'dialog_id': row['dialog_id'],
                'audio_a': row['audio_a'],
                'audio_b': row['audio_b'],
                'text_a': row['text_a'],
                'text_b': row['text_b'],
            })
    return pairs

def auto_pair_files(audio_dir: str, text_dir: str) -> List[Dict]:
    """
    自动配对：尝试通过文件名公共前缀将音频和文本组成对话。
    要求：每个对话必须能找到两段音频和两份文本。
    你可以根据自己的命名规则修改该函数。
    """
    audio_files = [os.path.join(audio_dir, f) for f in os.listdir(audio_dir)
                   if os.path.isfile(os.path.join(audio_dir, f))]
    text_files = [os.path.join(text_dir, f) for f in os.listdir(text_dir)
                  if os.path.isfile(os.path.join(text_dir, f))]

    # 建立不含扩展名的索引
    def base_no_ext(p): return os.path.splitext(os.path.basename(p))[0]

    audio_bases = {}
    for p in audio_files:
        b = base_no_ext(p)
        audio_bases.setdefault(b, []).append(p)

    text_bases = {}
    for p in text_files:
        b = base_no_ext(p)
        text_bases.setdefault(b, []).append(p)

    # 简单策略：根据去掉尾部说话人标签（如 _A/_B 或 -spk1/-spk2）后的前缀聚类
    def strip_suffix(b):
        return re.sub(r'([_-])(A|B|spk1|spk2|S1|S2)$', '', b, flags=re.IGNORECASE)

    clusters_audio = {}
    for b, paths in audio_bases.items():
        key = strip_suffix(b)
        clusters_audio.setdefault(key, []).extend(paths)

    clusters_text = {}
    for b, paths in text_bases.items():
        key = strip_suffix(b)
        clusters_text.setdefault(key, []).extend(paths)

    pairs = []
    for key in clusters_audio:
        auds = sorted(clusters_audio[key])
        txts = sorted(clusters_text.get(key, []))
        if len(auds) != 2 or len(txts) != 2:
            # 跳过不完整的对话
            continue
        dialog_id = key
        # 简单按文件名排序分配 A/B
        pairs.append({
            'dialog_id': dialog_id,
            'audio_a': auds[0],
            'audio_b': auds[1],
            'text_a': txts[0],
            'text_b': txts[1],
        })
    return pairs

# def process_dialog_pair(audio_a: str, audio_b: str, text_a: str, text_b: str,
#                         dialog_id: Optional[str], out_audio_dir: str) -> Dict:
#     """
#     处理一对对话：切分音频，合并为 ShareGPT 对话结构。
#     """
#     segs_a = parse_transcript_file(text_a)
#     segs_b = parse_transcript_file(text_b)
#     # 若文本中存在不同 spk_id/gender，以第一条为该声道的标签
#     spk_label_a = segs_a[0]['spk_id'] if segs_a else 'spkA'
#     spk_label_b = segs_b[0]['spk_id'] if segs_b else 'spkB'

#     if not dialog_id:
#         dialog_id = guess_dialog_id_from_pair(audio_a, audio_b)

#     cut_a = cut_audio_segments(audio_a, segs_a, out_audio_dir, dialog_id, spk_label_a)
#     cut_b = cut_audio_segments(audio_b, segs_b, out_audio_dir, dialog_id, spk_label_b)
#     turns = merge_turns_by_time(cut_a, cut_b)
#     dialog_json = build_sharegpt_dialog(dialog_id, turns)
#     return dialog_json


# def merge_segments_joint(segs_self: List[Dict], segs_other: List[Dict], merge_gap: float = 0.8) -> List[Dict]:
#     """
#     将同一说话人相邻分段在满足条件时合并：
#     - 两段之间的空隙 <= merge_gap（秒）
#     - 在 (prev.end, next.start) 时间区间内，另一位说话人没有发言（无重叠/占用）

#     返回合并后的新列表（保持按时间排序）。
#     """
#     if not segs_self:
#         return []

#     self_sorted = sorted(segs_self, key=lambda s: (s['start'], s['end']))
#     other_sorted = sorted(segs_other, key=lambda s: (s['start'], s['end']))

#     merged = []
#     cur = dict(self_sorted[0])  # 当前正在累积的段
#     j = 0  # 指向另一位说话人的分段

#     for nxt in self_sorted[1:]:
#         gap = max(0.0, nxt['start'] - cur['end'])
#         # 将 other 的指针推进到有可能与 (cur.end, nxt.start) 产生重叠的位置
#         while j < len(other_sorted) and other_sorted[j]['end'] <= cur['end']:
#             j += 1

#         # 检查另一说话人在 (cur.end, nxt.start) 是否占用时间
#         interrupted = False
#         k = j
#         while k < len(other_sorted):
#             o = other_sorted[k]
#             # 如果该段的开始已经超过 nxt.start，后面更不可能重叠，停止检查
#             if o['start'] >= nxt['start']:
#                 break
#             # 判断是否与 (cur.end, nxt.start) 区间发生占用/重叠：
#             # 条件：o.start < nxt.start 且 o.end > cur.end
#             if o['start'] < nxt['start'] and o['end'] > cur['end']:
#                 interrupted = True
#                 break
#             k += 1

#         if (gap <= merge_gap) and (not interrupted):
#             # 合并：扩大当前段的 end，其他元数据以 cur 为基准保留
#             cur['end'] = max(cur['end'], nxt['end'])
#             # 可选：合并文本 cur['text'] += ' ' + nxt['text']
#             # 这里不强制合并 text，因为最终输出用的是音频路径
#         else:
#             merged.append(cur)
#             cur = dict(nxt)

#     merged.append(cur)
#     return merged

def merge_segments_joint(segs_self: List[Dict], segs_other: List[Dict], merge_gap: float = 0.8) -> List[Dict]:
    """
    将同一说话人相邻分段在满足条件时合并：
    - 两段之间的空隙 <= merge_gap（秒）
    - 在 (prev.end, next.start) 时间区间内，另一位说话人没有发言（无重叠/占用）

    返回合并后的新列表（保持按时间排序）。
    """
    if not segs_self:
        return []

    self_sorted = sorted(segs_self, key=lambda s: (s['start'], s['end']))
    other_sorted = sorted(segs_other, key=lambda s: (s['start'], s['end']))

    merged = []
    cur = dict(self_sorted[0])  # 当前正在累积的段
    j = 0  # 指向另一位说话人的分段

    for nxt in self_sorted[1:]:
        gap = max(0.0, nxt['start'] - cur['end'])
        # 将 other 的指针推进到有可能与 (cur.end, nxt.start) 产生重叠的位置
        while j < len(other_sorted) and other_sorted[j]['end'] <= cur['end']:
            j += 1

        # 检查另一说话人在 (cur.end, nxt.start) 是否占用时间
        interrupted = False
        k = j
        while k < len(other_sorted):
            o = other_sorted[k]
            # 如果该段的开始已经超过 nxt.start，后面更不可能重叠，停止检查
            if o['start'] >= nxt['start']:
                break
            # 判断是否与 (cur.end, nxt.start) 区间发生占用/重叠：
            # 条件：o.start < nxt.start 且 o.end > cur.end
            if o['start'] < nxt['start'] and o['end'] > cur['end']:
                interrupted = True
                break
            k += 1

        if (gap <= merge_gap) and (not interrupted):
            # 合并：扩大当前段的 end，其他元数据以 cur 为基准保留
            cur['end'] = max(cur['end'], nxt['end'])
            # 可选：合并文本 cur['text'] += ' ' + nxt['text']
            # 这里不强制合并 text，因为最终输出用的是音频路径
        else:
            merged.append(cur)
            cur = dict(nxt)

    merged.append(cur)
    return merged

def process_dialog_pair(audio_a: str, audio_b: str, text_a: str, text_b: str,
                        dialog_id: Optional[str], out_audio_dir: str,
                        merge_gap: float = 0.8) -> Dict:
    """
    处理一对对话：先合并同说话人连续片段（在没有被另一人打断且间隔<=merge_gap时），
    再切分音频，最后导出 ShareGPT 对话结构。
    """
    segs_a = parse_transcript_file(text_a)
    segs_b = parse_transcript_file(text_b)

    # # 合并：跨说话人感知 + 间隔阈值
    # segs_a = merge_segments_joint(segs_a, segs_b, merge_gap=merge_gap)
    # segs_b = merge_segments_joint(segs_b, segs_a, merge_gap=merge_gap)

    # spk_label_a = segs_a[0]['spk_id'] if segs_a else 'spkA'
    # spk_label_b = segs_b[0]['spk_id'] if segs_b else 'spkB'

    # if not dialog_id:
    #     dialog_id = guess_dialog_id_from_pair(audio_a, audio_b)

    # cut_a = cut_audio_segments(audio_a, segs_a, out_audio_dir, dialog_id, spk_label_a)
    # cut_b = cut_audio_segments(audio_b, segs_b, out_audio_dir, dialog_id, spk_label_b)
    # turns = merge_turns_by_time(cut_a, cut_b)
    # dialog_json = build_sharegpt_dialog(dialog_id, turns)
    # return dialog_json
    # Merge within speaker with cross-speaker awareness
    segs_a = merge_segments_joint(segs_a, segs_b, merge_gap=merge_gap)
    segs_b = merge_segments_joint(segs_b, segs_a, merge_gap=merge_gap)

    # Labels (directory names)
    spk_label_a = segs_a[0]['spk_id'] if segs_a else 'spkA'
    spk_label_b = segs_b[0]['spk_id'] if segs_b else 'spkB'

    if not dialog_id:
        dialog_id = guess_dialog_id_from_pair(audio_a, audio_b)

    cut_a = cut_audio_segments(audio_a, segs_a, out_audio_dir, dialog_id, spk_label_a)
    cut_b = cut_audio_segments(audio_b, segs_b, out_audio_dir, dialog_id, spk_label_b)

    # Map A to user, B to assistant by default (change if needed)
    messages, audios = merge_turns_by_time(cut_a, cut_b, role_a='user', role_b='assistant')
    # messages, audios = collapse_consecutive_messages(messages, audios)
    # messages, audios = merge_turns_by_time(cut_a, cut_b, role_a='user', role_b='assistant') 
    messages, audios, user_audio_counts = collapse_consecutive_messages(messages, audios) 
    chunks = split_dialog_into_max_rounds(messages, audios, user_audio_counts, max_rounds=3)

    # dialog_json = build_target_dialog(messages, audios)

    return chunks

def collapse_consecutive_messages(messages: List[Dict], audios: List[str]) -> Tuple[List[Dict], List[str], List[int]]: 
    """ 合并相邻同角色消息并返回： 
    - new_messages: 折叠后的消息（user/assistant 交替） 
    - new_audios: 与折叠后 user 消息一一对应的音频路径流（按出现顺序串联） 
    - user_audio_counts: 长度与 new_messages 一致；new_messages[i] 若为 user，则给出其占用的音频数，否则为 0 
    """ 
    new_messages: List[Dict] = [] 
    new_audios: List[str] = [] 
    user_audio_counts: List[int] = []
    i = 0
    n = len(messages)
    audio_idx = 0  # 在旧 audios 中的消费下标

    while i < n:
        role = messages[i]['role']
        if role == 'user':
            # 合并连续 user（每条 user 原本都是一个 '<audio>'）
            j = i
            count_audio = 0
            while j < n and messages[j]['role'] == 'user':
                # 每条 user 都有一个 '<audio>'，占 1 个音频
                count_audio += 1
                j += 1
            # 生成合并后的 user 消息，content 为重复的 '<audio>'
            merged_content = "<audio>" * count_audio
            new_messages.append({'role': 'user', 'content': merged_content})
            user_audio_counts.append(count_audio)
            # 消费对应数量的音频路径
            new_audios.extend(audios[audio_idx:audio_idx + count_audio])
            audio_idx += count_audio
            i = j
        else:
            # 合并连续 assistant 文本
            j = i
            parts: List[str] = []
            while j < n and messages[j]['role'] == 'assistant':
                txt = (messages[j].get('content') or '').strip()
                if txt:
                    parts.append(txt)
                j += 1
            merged_txt = ' '.join(parts).strip()
            if merged_txt:
                new_messages.append({'role': 'assistant', 'content': merged_txt})
                user_audio_counts.append(0)
            i = j

    # 一致性校验：应当消费完全部 audios
    if audio_idx != len(audios):
        # 你也可以 raise ValueError(...) 让问题暴露更明显
        # 这里将剩余音频并入最后一个 user 消息，尽量不中断流程
        if new_messages:
            # 找到最后一个 user 消息，把剩余音频并进去，同时补足 content 和计数
            remaining = len(audios) - audio_idx
            for idx in range(len(new_messages) - 1, -1, -1):
                if new_messages[idx]['role'] == 'user':
                    new_messages[idx]['content'] += "<audio>" * remaining
                    new_audios.extend(audios[audio_idx:])
                    user_audio_counts[idx] += remaining
                    audio_idx = len(audios)
                    break

    return new_messages, new_audios, user_audio_counts


def split_dialog_into_max_rounds(messages: List[Dict], audios: List[str], user_audio_counts: List[int], max_rounds: int = 3) -> List[Dict]: 
    """ 将一个对话拆分为多个样本，每个样本最多包含 max_rounds 轮： - 一轮 = 1 条 user（可能包含多个 '<audio>'）+ 紧随的 0/1 条 assistant audios 仅对应 user 段；按 user_audio_counts 精确分配。 
    """ 
    chunks: List[Dict] = [] 
    i = 0 
    n = len(messages) 
    audio_idx = 0 # 在 audios 的消费下标
    while i < n:
        rounds = 0
        chunk_msgs: List[Dict] = []
        chunk_audios: List[str] = []

        # 可选：将开头的 assistant 并入样本但不计轮
        while i < n and messages[i]['role'] == 'assistant' and rounds == 0:
            txt = (messages[i].get('content') or '').strip()
            if txt:
                chunk_msgs.append({'role': 'assistant', 'content': txt})
            i += 1

        # 装入最多 max_rounds 轮
        while i < n and rounds < max_rounds:
            if messages[i]['role'] != 'user':
                break

            # 1) user
            u_msg = messages[i]
            k = user_audio_counts[i] if 0 <= i < len(user_audio_counts) else 0
            chunk_msgs.append({'role': 'user', 'content': u_msg.get('content') or '&lt;audio>' * k})
            if k > 0:
                chunk_audios.extend(audios[audio_idx:audio_idx + k])
                audio_idx += k
            i += 1

            # 2) 紧随其后的至多一条 assistant
            if i < n and messages[i]['role'] == 'assistant':
                a_txt = (messages[i].get('content') or '').strip()
                if a_txt:
                    chunk_msgs.append({'role': 'assistant', 'content': a_txt})
                i += 1

            rounds += 1

        if chunk_msgs:
            chunks.append({'messages': chunk_msgs, 'audios': chunk_audios})
        else:
            # 防御：避免极端空文本导致死循环
            i += 1

    # 校验：audios 是否被完全消费
    total_in_chunks = sum(len(c['audios']) for c in chunks)
    if total_in_chunks != len(audios):
        # 你可以改为 raise，以便尽快发现问题
        print(f"[warn] audio paths mismatch: used {total_in_chunks} / total {len(audios)}")

    return chunks


def main():
    parser = argparse.ArgumentParser(description="Split two-speaker dialogs and export ShareGPT JSON with audio paths.")
    parser.add_argument('--audio_dir', type=str, required=False, help='音频文件夹路径（自动配对模式）')
    parser.add_argument('--text_dir', type=str, required=False, help='文本文件夹路径（自动配对模式）')
    parser.add_argument('--manifest', type=str, required=False, help='CSV 清单文件路径（列：dialog_id,audio_a,audio_b,text_a,text_b）')
    parser.add_argument('--out_audio_dir', type=str, required=True, help='切分后音频输出目录')
    parser.add_argument('--out_json', type=str, required=True, help='最终 ShareGPT JSON 输出路径（聚合所有对话）')
    parser.add_argument('--merge_gap', type=float, default=0.8, help='同说话人相邻片段的最大合并间隔(秒)')
    args = parser.parse_args()
    if args.manifest:
        pairs = read_manifest(args.manifest)
    else:
        if not args.audio_dir or not args.text_dir:
            raise ValueError("自动配对需要提供 --audio_dir 与 --text_dir；或使用 --manifest 指定清单。")
        pairs = auto_pair_files(args.audio_dir, args.text_dir)

    if not pairs:
        raise ValueError("未找到任何可处理的对话配对。")

    all_dialogs = []
    for p in pairs:
        dialog_json = process_dialog_pair(
            audio_a=p['audio_a'],
            audio_b=p['audio_b'],
            text_a=p['text_a'],
            text_b=p['text_b'],
            dialog_id=p.get('dialog_id'),
            out_audio_dir=args.out_audio_dir,
            merge_gap=args.merge_gap
        )
        all_dialogs.extend(dialog_json)
        # chunks = split_dialog_into_max_rounds(dialog_json['messages'], dialog_json['audios'], max_rounds=3) 
        # all_dialogs.extend(chunks)

    with open(args.out_json, 'w', encoding='utf-8') as f:
        json.dump(all_dialogs, f, ensure_ascii=False, indent=2)

    print(f"完成：输出 {len(all_dialogs)} 个对话到 {args.out_json}")

if __name__ == '__main__':
    main()

# python data/processing_sylvan/audio_multi_stream_process.py --audio_dir /nfs1/chain/datasets/WAV --text_dir /nfs1/chain/datasets/TXT --out_audio_dir /nfs1/chain/datasets/split_audio --out_json /nfs1/chain/LLaMA-Factory/data/audio_5h_multi_turn.json --manifest /nfs1/chain/LLaMA-Factory/data/processing_sylvan/multi-turn-audio.csv