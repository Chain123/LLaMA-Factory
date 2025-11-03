import os
import csv
import argparse
from collections import defaultdict

def split_prefix_and_speaker(basename_no_ext: str):
    """
    输入不带扩展名的文件名：dailogueID_sessionID_num_speakerID
    返回 (prefix, speaker_id)
    其中 prefix = dailogueID_sessionID_num，speaker_id = 最后一段
    """
    parts = basename_no_ext.split('_')
    if len(parts) < 2:
        # 兜底：没有下划线就视为整体为前缀，speaker 为空
        return basename_no_ext, ''
    prefix = '_'.join(parts[:-1])
    speaker_id = parts[-1]
    return prefix, speaker_id

def index_files_by_prefix_and_speaker(root_dir: str, valid_exts):
    """
    返回结构：
    {
      prefix: {
        speaker_id: absolute_path
      }
    }
    """
    index = defaultdict(dict)
    for fname in os.listdir(root_dir):
        fpath = os.path.join(root_dir, fname)
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in valid_exts:
            continue
        base = os.path.splitext(fname)[0]
        prefix, speaker = split_prefix_and_speaker(base)
        if not speaker:
            # 没有 speaker_id，跳过
            continue
        # 若同一 prefix+speaker 出现多次，后者会覆盖前者，可按需改为告警
        index[prefix][speaker] = os.path.abspath(fpath)
    return index

def build_manifest(audio_dir: str, text_dir: str, out_csv: str):
    audio_index = index_files_by_prefix_and_speaker(audio_dir, valid_exts={'.wav', '.mp3', '.flac', '.m4a', '.ogg'})
    text_index  = index_files_by_prefix_and_speaker(text_dir,  valid_exts={'.txt'})

    rows = []
    warnings = []

    # 只遍历两侧都存在的前缀
    common_prefixes = sorted(set(audio_index.keys()) & set(text_index.keys()))
    for prefix in common_prefixes:
        aud_speakers = set(audio_index[prefix].keys())
        txt_speakers = set(text_index[prefix].keys())
        common_speakers = sorted(aud_speakers & txt_speakers)

        if len(common_speakers) < 2:
            warnings.append(f"[SKIP] prefix={prefix} 共同说话人不足2位 (audio={sorted(aud_speakers)}, text={sorted(txt_speakers)})")
            continue

        if len(common_speakers) > 2:
            warnings.append(f"[WARN] prefix={prefix} 共同说话人超过2位，将仅选择前两位：{common_speakers[:2]} 全部={common_speakers}")

        spk_a, spk_b = common_speakers[:2]
        audio_a = audio_index[prefix].get(spk_a)
        audio_b = audio_index[prefix].get(spk_b)
        text_a  = text_index[prefix].get(spk_a)
        text_b  = text_index[prefix].get(spk_b)

        # 再次确认对应路径都存在
        if not (audio_a and audio_b and text_a and text_b):
            warnings.append(f"[SKIP] prefix={prefix} A/B 路径缺失 (audio_a={bool(audio_a)} audio_b={bool(audio_b)} text_a={bool(text_a)} text_b={bool(text_b)})")
            continue

        rows.append({
            'dialog_id': prefix,
            'audio_a': audio_a,
            'audio_b': audio_b,
            'text_a': text_a,
            'text_b': text_b
        })

    # 将只在某一侧出现的前缀也提示出来
    audio_only = sorted(set(audio_index.keys()) - set(text_index.keys()))
    text_only  = sorted(set(text_index.keys()) - set(audio_index.keys()))
    for p in audio_only:
        warnings.append(f"[INFO] 仅在音频中发现的前缀：{p}")
    for p in text_only:
        warnings.append(f"[INFO] 仅在文本中发现的前缀：{p}")

    # 写出 CSV
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    with open(out_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['dialog_id','audio_a','audio_b','text_a','text_b'])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"已生成 manifest：{out_csv}，对话数={len(rows)}")
    if warnings:
        print("提示/告警：")
        for w in warnings:
            print(" -", w)

def main():
    ap = argparse.ArgumentParser(description="根据音频/文本文件夹生成两说话人对话的 manifest CSV")
    ap.add_argument('--audio_dir', required=True, help='音频文件夹（文件名形如 dailogueID_sessionID_num_speakerID.wav）')
    ap.add_argument('--text_dir', required=True, help='文本文件夹（文件名形如 dailogueID_sessionID_num_speakerID.txt）')
    ap.add_argument('--out_csv', required=True, help='输出 CSV 路径')
    args = ap.parse_args()
    build_manifest(args.audio_dir, args.text_dir, args.out_csv)

if __name__ == '__main__':
    main()