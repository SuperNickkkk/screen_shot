import openai
import os
from pydub import AudioSegment
import subprocess
import requests
import json
import shlex
import re
import platform

class OpenAITranscriptionService:
    def __init__(self):
        self.api_key = ""
        self.transcription_url = "https://api.chatanywhere.tech/v1/audio/transcriptions"

    def transcribe_audio(self, audio_file_path):
        """
        使用指定的 API 地址转录音频文件。
        """
        try:
            with open(audio_file_path, "rb") as audio_file:
                files = {"file": audio_file}
                headers = {"Authorization": f"Bearer {self.api_key}"}
                data = {"model": "whisper-1","prompt": "用户正在制作srt字幕文件,请你返回中文简体文字，如果用户使用了英文，则同时正确返回英文", "response_format": "verbose_json", "language": "zh"}
                
                response = requests.post(self.transcription_url, headers=headers, files=files, data=data)
                response.raise_for_status()
                
                transcript = response.json()
                return transcript
        except Exception as e:
            print(f"转录过程中出错: {str(e)}")
            return None

    def generate_srt_subtitles(self, transcript):
        """
        根据转录文本生成 SRT 格式的字幕，优化换行和换页逻辑。
        """
        srt_content = ""
        subtitle_number = 1
        current_lines = []
        current_start_time = None

        segments = transcript['segments']
        for i, segment in enumerate(segments):
            words = self.split_text(segment['text'].strip())
            start_time = self.format_time(segment['start'])
            end_time = self.format_time(segment['end'])

            if not current_start_time:
                current_start_time = start_time

            for word in words:
                if len(' '.join(current_lines + [word])) > 40 or word in ['.', '。', '!', '！', '?', '？']:
                    # 如果当前行加上新单词超过40个字符，或遇到句子结束标点，就换行
                    srt_content += f"{subtitle_number}\n{current_start_time} --> {end_time}\n{' '.join(current_lines)}\n\n"
                    subtitle_number += 1
                    current_lines = [word] if word not in ['.', '。', '!', '！', '?', '？'] else []
                    current_start_time = None
                else:
                    current_lines.append(word)

            # 处理段落结束
            if current_lines:
                srt_content += f"{subtitle_number}\n{current_start_time} --> {end_time}\n{' '.join(current_lines)}\n\n"
                subtitle_number += 1
                current_lines = []
                current_start_time = None

        return srt_content

    def split_text(self, text):
        """
        将文本分割成单词或字符，保留标点符号。
        """
        # 使用正则表达式分割文本，保留标点符号
        return re.findall(r'\w+|[^\s\w]', text)

    def format_time(self, seconds):
        """
        将秒数格式化为 SRT 时间戳格式。
        """
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}".replace('.', ',')

    def add_subtitles_to_video(self, video_path, srt_path, output_path):
        """
        使用 FFmpeg 将字幕添加到视频中。
        """
        try:
            # 使用 os.path.abspath 获取绝对路径
            video_path = os.path.abspath(video_path)
            srt_path = os.path.abspath(srt_path)
            output_path = os.path.abspath(output_path)

            # 打印文件路径以进行调试
            print(f"添加字幕 - 视频文件路径: {video_path}")
            print(f"添加字幕 - 字幕文件路径: {srt_path}")
            print(f"添加字幕 - 输出文件路径: {output_path}")

            # 检查 SRT 文件是否存在
            if os.path.exists(srt_path):
                print(f"SRT 文件确实存在于: {srt_path}")
                # 打印 SRT 文件的前几行
                with open(srt_path, 'r', encoding='utf-8') as f:
                    print(f"SRT 文件内容预览:\n{f.read(500)}...")  # 读取前500个字符
            else:
                print(f"错误：SRT 文件不存在于: {srt_path}")
                raise FileNotFoundError(f"SRT 文件不存在: {srt_path}")

            # 构建 FFmpeg 命令
            command = [
                'ffmpeg',
                '-i', video_path,
                '-vf', f"subtitles='{srt_path}':force_style='FontName=SimHei,FontSize=24,PrimaryColour=white,OutlineColour=black,BorderStyle=3'",
                '-c:a', 'copy',
                '-y',
                output_path
            ]

            # 打印完整的 FFmpeg 命令
            print("执行的 FFmpeg 命令:", ' '.join(command))

            # 使用 subprocess.run 执行命令，并捕获输出
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            print("字幕已成功添加到视频中。")
            print(f"FFmpeg 输出: {result.stdout}")
        except subprocess.CalledProcessError as e:
            print(f"添加字幕时出错: {e.stdout}\n{e.stderr}")
            raise
        except Exception as e:
            print(f"发生未预期的错误: {str(e)}")
            raise

def process_video_with_subtitles(video_path, output_path, srt_path):
    """
    处理视频，添加字幕，并生成单独的SRT文件。
    """
    service = OpenAITranscriptionService()

    # 使用绝对路径
    audio_path = os.path.abspath("temp_audio.wav")
    video_path = os.path.abspath(video_path)
    output_path = os.path.abspath(output_path)
    srt_path = os.path.abspath(srt_path)

    # 打印所有路径以进行调试
    print(f"处理视频 - 视频文件路径: {video_path}")
    print(f"处理视频 - 输出文件路径: {output_path}")
    print(f"处理视频 - 字幕文件路径: {srt_path}")
    print(f"处理视频 - 临时音频文件路径: {audio_path}")

    # 提取音频
    extract_audio_command = [
        'ffmpeg',
        '-i', video_path,
        '-vn',
        '-acodec', 'pcm_s16le',
        '-ar', '16000',
        '-ac', '1',
        '-y',
        audio_path
    ]

    try:
        # 使用 subprocess.run 执行命令，并捕获输出
        result = subprocess.run(extract_audio_command, check=True, capture_output=True, text=True)
        print("音频提取成功")
        print(f"FFmpeg 输出: {result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"音频提取失败: {e.stdout}\n{e.stderr}")
        raise

    # 转录音频
    transcript = service.transcribe_audio(audio_path)
    if transcript:
        # 生成 SRT 字幕
        srt_content = service.generate_srt_subtitles(transcript)
        
        # 保存 SRT 文件
        with open(srt_path, "w", encoding="utf-8") as srt_file:
            srt_file.write(srt_content)
        
        print(f"SRT 文件已保存到: {srt_path}")
        print(f"SRT 文件内容预览:\n{srt_content[:500]}...")  # 打印前500个字符

        # 检查 SRT 文件是否存在
        if os.path.exists(srt_path):
            print(f"SRT 文件确实存在于: {srt_path}")
        else:
            print(f"错误：SRT 文件不存在于: {srt_path}")

        # 将字幕添加到视频
        service.add_subtitles_to_video(video_path, srt_path, output_path)

        # 不删除临时音频文件
        print(f"临时音频文件保存在: {audio_path}")
    else:
        print("转录失败，无法生成字幕。")
        raise Exception("转录失败")

    # 返回所有生成的文件路径
    return video_path, srt_path, output_path, audio_path
