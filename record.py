import numpy as np
import cv2
import sounddevice as sd
import soundfile as sf
import tempfile
import os
import time
import threading
import d3dshot
import ffmpeg
from queue import Queue
from collections import deque
from scipy import signal
import pyautogui

class ScreenRecorder:
    def __init__(self):
        self.recording = False
        self.audio_level = 0
        self.temp_dir = tempfile.mkdtemp()
        self.audio_thread = None
        self.video_thread = None
        self.audio_frames = []
        self.video_frames = Queue()
        self.d3d = d3dshot.create(capture_output="numpy")
        self.audio_sample_rate = 44100
        self.audio_channels = 2
        self.audio_dtype = 'float32'
        self.is_paused = False
        self.pause_event = threading.Event()
        self.video_fps = 30.0
        self.frame_duration = 1 / self.video_fps
        self.start_time = None
        self.pause_start_time = None
        self.total_pause_time = 0
        self.recording_area = None
        self.sync_buffer = deque(maxlen=100)
        self.start_event = threading.Event()
        self.pause_time = 0
        self.last_frame_time = 0
        self.last_audio_time = 0
        self.frame_count = 0
        self.audio_sample_count = 0
        self.recording_start_time = None
        self.test_audio_running = False
        self.camera_enabled = False
        self.camera = None
        self.camera_frame = None
        self.mouse_position = (0, 0)  # 新增: 存储鼠标位置

    def set_recording_area(self, rect):
        self.recording_area = rect

    def record_audio(self, audio_sample_rate, device_index):
        self.start_event.wait()
        self.recording_start_time = time.perf_counter()
        with sd.InputStream(samplerate=audio_sample_rate, channels=self.audio_channels, 
                            dtype=self.audio_dtype, callback=self.audio_callback, 
                            device=device_index, latency='low'):
            while self.recording:
                if not self.is_paused:
                    sd.sleep(100)
                else:
                    self.pause_event.wait()

    def audio_callback(self, indata, frames, time_info, status):
        if self.is_paused:
            return
        current_time = time.perf_counter() - self.recording_start_time - self.total_pause_time
        self.audio_frames.append((current_time, indata.copy()))
        self.audio_level = np.max(np.abs(indata))
        self.last_audio_time = current_time
        self.audio_sample_count += frames

    def record_video(self):
        self.recording_start_time = time.perf_counter()
        self.start_event.set()
        next_frame_time = self.recording_start_time
        while self.recording:
            if not self.is_paused:
                current_time = time.perf_counter()
                if current_time >= next_frame_time:
                    frame = self.d3d.screenshot()
                    self.mouse_position = pyautogui.position()  # 获取鼠标位置
                    if self.recording_area:
                        x, y, w, h = self.recording_area.getRect()
                        frame = frame[y:y+h, x:x+w]
                        self.mouse_position = (self.mouse_position[0] - x, self.mouse_position[1] - y)  # 调整鼠标位置相对于录制区域
                    
                    # 在帧上绘制鼠标指针
                    frame_with_cursor = self.draw_mouse_pointer(frame)
                    
                    frame_time = current_time - self.recording_start_time - self.total_pause_time
                    self.video_frames.put((frame_time, frame_with_cursor))
                    next_frame_time = self.recording_start_time + (self.frame_count + 1) * self.frame_duration + self.total_pause_time
                    self.last_frame_time = frame_time
                    self.frame_count += 1
                else:
                    time.sleep(0.001)
            else:
                self.pause_event.wait()

    def draw_mouse_pointer(self, frame):
        # 创建一个帧的副本，以便在上面绘制而不影响原始帧
        frame_with_cursor = frame.copy()
        x, y = self.mouse_position
        if 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]:
            # 绘制一个更明显的鼠标指针
            cv2.circle(frame_with_cursor, (int(x), int(y)), 10, (0, 255, 0), 2)  # 绿色圆圈
            cv2.line(frame_with_cursor, (int(x), int(y)), (int(x), int(y) - 10), (0, 255, 0), 2)  # 上
            cv2.line(frame_with_cursor, (int(x), int(y)), (int(x), int(y) + 10), (0, 255, 0), 2)  # 下
            cv2.line(frame_with_cursor, (int(x), int(y)), (int(x) - 10, int(y)), (0, 255, 0), 2)  # 左
            cv2.line(frame_with_cursor, (int(x), int(y)), (int(x) + 10, int(y)), (0, 255, 0), 2)  # 右
        return frame_with_cursor

    def start_camera(self):
        if self.camera is None:
            self.camera = cv2.VideoCapture(0)
        self.camera_enabled = True

    def stop_camera(self):
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        self.camera_enabled = False

    def get_camera_frame(self):
        if self.camera_enabled and self.camera:
            ret, frame = self.camera.read()
            if ret:
                self.camera_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                return self.camera_frame
        return None

    def record_screen(self, output_file, record_audio=True, output_format='mp4', device_index=None, volume=1.0):
        self.recording = True
        self.is_paused = False
        self.pause_event.set()
        self.start_event.clear()

        if record_audio:
            self.audio_thread = threading.Thread(target=self.record_audio, args=(self.audio_sample_rate, device_index))
            self.audio_thread.start()

        self.video_thread = threading.Thread(target=self.record_video)
        self.video_thread.start()

        try:
            self.recording_start_time = time.perf_counter()
            next_frame_time = self.recording_start_time
            while self.recording:
                if not self.is_paused:
                    current_time = time.perf_counter()
                    if current_time >= next_frame_time:
                        frame = self.d3d.screenshot()
                        if self.recording_area:
                            x, y, w, h = self.recording_area.getRect()
                            frame = frame[y:y+h, x:x+w]

                        frame_time = current_time - self.recording_start_time - self.total_pause_time
                        self.video_frames.put((frame_time, frame))
                        next_frame_time = self.recording_start_time + (self.frame_count + 1) * self.frame_duration + self.total_pause_time
                        self.last_frame_time = frame_time
                        self.frame_count += 1
                    else:
                        time.sleep(0.001)
                else:
                    self.pause_event.wait()
        except Exception as e:
            print(f"Recording error: {e}")
        finally:
            self.stop_recording()
            self.process_recorded_data(output_file, output_format, volume)

    def check_sync(self):
        if len(self.sync_buffer) > 30:  # 减少检查间隔
            audio_times = [t for type, t in self.sync_buffer if type == 'audio']
            video_times = [t for type, t in self.sync_buffer if type == 'video']
            if audio_times and video_times:
                sync_diff = np.mean(audio_times) - np.mean(video_times)
                if abs(sync_diff) > 0.05:  # 如果音视频差异超过50ms
                    print(f"Sync adjustment needed: {sync_diff:.3f}s")
                    self.adjust_sync(sync_diff)
        self.sync_buffer.clear()  # 清空缓冲区，避免旧数据影响

    def adjust_sync(self, sync_diff):
        # 调整视频时间戳
        adjusted_video_frames = Queue()
        while not self.video_frames.empty():
            timestamp, frame = self.video_frames.get()
            adjusted_video_frames.put((timestamp + sync_diff, frame))
        self.video_frames = adjusted_video_frames
        self.last_frame_time += sync_diff

    def process_recorded_data(self, output_file, output_format, volume):
        temp_video = os.path.join(self.temp_dir, f'temp_video.{output_format}')
        temp_audio = os.path.join(self.temp_dir, 'temp_audio.wav')

        # 处理视频帧
        fourcc = cv2.VideoWriter_fourcc(*self.get_fourcc(output_format))
        out = None
        frame_times = []
        while not self.video_frames.empty():
            timestamp, frame = self.video_frames.get()
            frame_times.append(timestamp)
            if out is None:
                out = cv2.VideoWriter(temp_video, fourcc, self.video_fps, (frame.shape[1], frame.shape[0]))
            out.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        
        if out:
            out.release()
        
        # 计算实际帧率
        if len(frame_times) > 1:
            actual_fps = (len(frame_times) - 1) / (frame_times[-1] - frame_times[0])
            print(f"Actual video FPS: {actual_fps:.2f}")
            print(f"Total frames: {self.frame_count}")
            print(f"Total video duration: {frame_times[-1]:.3f} seconds")

        # 处理音频帧
        if self.audio_frames:
            audio_data = np.concatenate([frame for _, frame in self.audio_frames], axis=0)
            audio_data = np.clip(audio_data * volume, -1, 1)
            
            print(f"Total audio samples: {self.audio_sample_count}")
            print(f"Total audio duration: {self.audio_sample_count / self.audio_sample_rate:.3f} seconds")
            
            sf.write(temp_audio, audio_data, self.audio_sample_rate)

            # 使用 FFmpeg 合并音视频
            self.merge_audio_video(temp_video, temp_audio, output_file, output_format)
        else:
            os.rename(temp_video, output_file)

        # 重置计数器和时间戳
        self.frame_count = 0
        self.audio_sample_count = 0
        self.last_frame_time = 0
        self.last_audio_time = 0
        self.total_pause_time = 0
        self.recording_start_time = None

    def toggle_pause(self):
        if self.is_paused:
            # 继续录制
            pause_duration = time.perf_counter() - self.pause_start_time
            self.total_pause_time += pause_duration
            self.is_paused = False
            self.pause_event.set()
            print(f"继续录制，暂停时长: {pause_duration:.3f}秒")
        else:
            # 暂停录制
            self.pause_start_time = time.perf_counter()
            self.is_paused = True
            self.pause_event.clear()
            print("暂停录制")

        self.adjust_sync_after_pause()

    def adjust_sync_after_pause(self):
        if self.last_frame_time > 0 and self.last_audio_time > 0:
            sync_diff = self.last_audio_time - self.last_frame_time
            if abs(sync_diff) > 0.05:  # 如果差异超过50ms
                print(f"暂停后同步调整: {sync_diff:.3f}秒")
                self.adjust_sync(sync_diff)

    def stop_recording(self):
        self.recording = False
        self.is_paused = False
        self.pause_event.set()

    def get_audio_level(self):
        return self.audio_level

    def cleanup(self):
        if self.temp_dir:
            try:
                for file in os.listdir(self.temp_dir):
                    os.remove(os.path.join(self.temp_dir, file))
                os.rmdir(self.temp_dir)
            except Exception:
                pass
            finally:
                self.temp_dir = None

    def get_fourcc(self, format):
        fourcc_dict = {
            'mp4': 'mp4v',
            'avi': 'XVID',
            'mov': 'MJPG'
        }
        return fourcc_dict.get(format, 'mp4v')

    def merge_audio_video(self, video_file, audio_file, output_file, output_format):
        try:
            video = ffmpeg.input(video_file)
            audio = ffmpeg.input(audio_file)
            out = ffmpeg.output(video, audio, output_file, 
                                vcodec='libx264', 
                                acodec='aac', 
                                video_bitrate='5000k', 
                                audio_bitrate='192k', 
                                r=self.video_fps, 
                                strict='experimental',
                                vsync='cfr')
            out = out.overwrite_output()
            ffmpeg.run(out, capture_stdout=True, capture_stderr=True)
        except Exception as e:
            print(f"Error during merge: {str(e)}")

    def reset(self):
        self.recording = False
        self.is_paused = False
        self.audio_level = 0
        if self.audio_thread:
            self.audio_thread.join()
        self.audio_thread = None
        if self.temp_dir:
            self.cleanup()
        self.temp_dir = tempfile.mkdtemp()
        self.pause_event.set()
        self.start_time = None
        self.pause_start_time = None
        self.total_pause_time = 0
        self.audio_frames = []

    def test_audio(self, device_index):
        self.test_audio_running = True
        with sd.InputStream(device=device_index, channels=self.audio_channels, 
                            samplerate=self.audio_sample_rate, callback=self.test_audio_callback):
            while self.test_audio_running:
                time.sleep(0.1)

    def test_audio_callback(self, indata, frames, time, status):
        if status:
            print(status)
        self.audio_level = np.max(np.abs(indata))

    def stop_audio_test(self):
        self.test_audio_running = False