import sys
import traceback
import logging
import time
import os
import threading
import math
import sounddevice as sd
import subprocess
import tempfile
import shutil
import shlex
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout, 
                             QLabel, QFileDialog, QProgressBar, QComboBox, QStyleFactory, 
                             QFrame, QSizePolicy, QSlider, QRubberBand, QShortcut, QCheckBox, QMessageBox)
from PyQt5.QtCore import Qt, QPoint, QTimer, pyqtSignal, QSize, QPropertyAnimation, QEasingCurve, QRect, QEvent
from PyQt5.QtGui import QIcon, QFont, QColor, QPalette, QPainter, QPixmap, QPen, QKeySequence, QImage
from PyQt5.QtSvg import QSvgRenderer
from record import ScreenRecorder
from openai_server import OpenAITranscriptionService, process_video_with_subtitles
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip
from moviepy.video.tools.subtitles import SubtitlesClip
import pysrt
from moviepy.config import change_settings
import ffmpeg

# 设置日志记录
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# 设置 ImageMagick 的路径
imagemagick_path = r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"  # 根您的安装路径调整
change_settings({"IMAGEMAGICK_BINARY": imagemagick_path})

def exception_hook(exctype, value, tb):
    error_msg = ''.join(traceback.format_exception(exctype, value, tb))
    print("An error occurred:")
    print(error_msg)
    logging.error("Uncaught exception: %s", error_msg)
    QMessageBox.critical(None, "Error", f"An unexpected error occurred:\n\n{error_msg}")

sys.excepthook = exception_hook

# 设置更详细的日志记录
logging.basicConfig(filename='screen_recorder.log', level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class ModernButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFont(QFont('Segoe UI', 10))
        self.setMinimumHeight(40)
        self.setStyleSheet("""
            QPushButton {
                background-color: #4a4a4a;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QPushButton:pressed {
                background-color: #3a3a3a;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #808080;
            }
        """)

class ModernComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont('Segoe UI', 10))
        self.setMinimumHeight(40)
        self.setStyleSheet("""
            QComboBox {
                background-color: #4a4a4a;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 5px 15px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border-left-width: 1px;
                border-left-color: #1e1e1e;
                border-left-style: solid;
            }
            QComboBox QAbstractItemView {
                background-color: #4a4a4a;
                color: white;
                selection-background-color: #5a5a5a;
            }
        """)

class RecordingIcon(QWidget):
    clicked = pyqtSignal()
    double_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(100, 100)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(50)
        self.angle = 0
        self.audio_level = 0
        self.is_paused = False
        self.is_stopping = False
        self.drag_position = None
        self.hover_start_time = None
        self.show_tooltip = False
        self.tooltip_timer = QTimer(self)
        self.tooltip_timer.setSingleShot(True)
        self.tooltip_timer.timeout.connect(self.show_tooltip_text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制透明圆形背景
        painter.setBrush(QColor(46, 46, 46, 200))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 100, 100)

        if self.is_stopping:
            # 绘制停止指示（方形）
            painter.setBrush(QColor(255, 0, 0))
            painter.drawRect(35, 35, 30, 30)
        elif self.is_paused:
            # 绘制暂停指示（两个竖条）
            painter.setBrush(QColor(255, 165, 0))
            painter.drawRect(35, 35, 10, 30)
            painter.drawRect(55, 35, 10, 30)
        else:
            # 绘制制指示（圆点）
            painter.setBrush(QColor(255, 0, 0))
            painter.drawEllipse(40, 40, 20, 20)

        # 绘制旋转的圆弧
        if not self.is_paused and not self.is_stopping:
            painter.setPen(QPen(QColor(255, 255, 255), 3))
            painter.drawArc(5, 5, 90, 90, self.angle * 16, 60 * 16)

        # 绘制声波指示器
        painter.setPen(Qt.NoPen)
        for i in range(3):
            opacity = min(1.0, self.audio_level * (3 - i) / 3)
            color = QColor(255, 255, 255, int(opacity * 100))
            painter.setBrush(color)
            size = 80 - i * 20
            painter.drawEllipse(50 - size/2, 50 - size/2, size, size)

        # 绘制悬停提示文字
        if self.show_tooltip:
            painter.setFont(QFont('Arial', 8))
            painter.setPen(Qt.white)
            painter.drawText(0, 0, 100, 100, Qt.AlignCenter, "单击暂停\n双击停止")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_position = None
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()

    def enterEvent(self, event):
        self.hover_start_time = time.time()
        self.tooltip_timer.start(500)  # 0.5秒后显示提示文字

    def leaveEvent(self, event):
        self.hover_start_time = None
        self.tooltip_timer.stop()
        self.show_tooltip = False
        self.update()

    def show_tooltip_text(self):
        self.show_tooltip = True
        self.update()

    def update(self):
        if not self.is_paused and not self.is_stopping:
            self.angle = (self.angle + 30) % 360
        super().update()

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        self.update()

    def start_stop_animation(self):
        self.is_stopping = True
        self.update()

    def set_audio_level(self, level):
        self.audio_level = level
        self.update()

class AreaSelectionWidget(QWidget):
    area_selected = pyqtSignal(QRect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.rubberband = QRubberBand(QRubberBand.Rectangle, self)
        self.origin = QPoint()

    def mousePressEvent(self, event):
        self.origin = event.pos()
        self.rubberband.setGeometry(QRect(self.origin, QSize()))
        self.rubberband.show()

    def mouseMoveEvent(self, event):
        self.rubberband.setGeometry(QRect(self.origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event):
        self.rubberband.hide()
        selected_rect = QRect(self.origin, event.pos()).normalized()
        self.area_selected.emit(selected_rect)
        self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setBrush(QColor(0, 0, 0, 100))
        painter.setPen(Qt.NoPen)
        painter.drawRect(self.rect())

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self.parent(), 'recording_icon'):
            self.parent().recording_icon.raise_()

class CameraPreviewWindow(QWidget):
    camera_closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)  # 设置窗口背景透明
        self.setStyleSheet("background-color: transparent;")  # 设置背景透明
        
        self.preview_label = QLabel(self)
        self.preview_label.setStyleSheet("background-color: transparent;")  # 设置标签背景透明
        
        # 添加关闭按钮
        self.close_button = QPushButton("×", self)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 0, 0, 150);
                color: white;
                border: none;
                font-size: 16px;
                font-weight: bold;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: rgba(255, 0, 0, 200);
            }
        """)
        self.close_button.clicked.connect(self.close_camera)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)  # 移除布局边距
        layout.addWidget(self.close_button, 0, Qt.AlignRight | Qt.AlignTop)
        layout.addWidget(self.preview_label)
        self.setLayout(layout)
        
        self.setGeometry(100, 100, 320, 240)  # 设置初始位置和大小
        self.dragging = False
        self.offset = QPoint()

    def close_camera(self):
        self.hide()
        self.camera_closed.emit()

    def update_preview(self, frame):
        if frame is not None:
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            q_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_image).scaled(320, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview_label.setPixmap(pixmap)
            self.resize(pixmap.width(), pixmap.height())  # 调整窗口大小以适应图像

    def move_to_bottom_right(self):
        screen_geometry = QApplication.desktop().screenGeometry()
        self.move(screen_geometry.width() - self.width() - 20, 
                  screen_geometry.height() - self.height() - 20)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.offset = event.pos()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(event.globalPos() - self.offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False

    def enterEvent(self, event):
        self.setCursor(Qt.OpenHandCursor)

    def leaveEvent(self, event):
        self.setCursor(Qt.ArrowCursor)

class ScreenRecorderUI(QWidget):
    recording_stopped = pyqtSignal()
    recording_failed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.initUI()
        self.check_ffmpeg()
        self.recorder = ScreenRecorder()
        self.recording_thread = None
        self.audio_level_timer = QTimer(self)
        self.audio_level_timer.timeout.connect(self.update_audio_level)
        self.recording_time = 0
        self.recording_timer = QTimer(self)
        self.recording_timer.timeout.connect(self.update_recording_time)

        self.recording_stopped.connect(self.on_recording_stopped)
        self.recording_failed.connect(self.on_recording_failed)

        self.recording_icon = RecordingIcon()
        self.recording_icon.clicked.connect(self.toggle_pause_recording)
        self.recording_icon.double_clicked.connect(self.stop_recording)

        self.rubberband = None
        self.origin = QPoint()
        self.current = QPoint()
        self.selected_area = None
        
        # 修改快捷键设置
        # self.shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        # self.shortcut.activated.connect(self.start_area_selection)
        # self.shortcut.setContext(Qt.ApplicationShortcut)  # 设置为应用程序范围捷键

        # 添加过滤器
        # QApplication.instance().installEventFilter(self)

        self.subtitle_enabled = False

        self.camera_preview = QLabel(self)
        self.camera_preview.setFixedSize(320, 240)
        self.camera_preview.hide()
        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self.update_camera_preview)

        self.camera_preview_window = CameraPreviewWindow()
        self.camera_preview_window.camera_closed.connect(self.stop_camera)
        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self.update_camera_preview)

    def initUI(self):
        self.setWindowTitle('Elite Screen Recorder')
        self.setGeometry(300, 300, 400, 500)
        self.setStyleSheet("""
            QWidget {
                background-color: #2e2e2e;
                color: white;
            }
            QLabel {
                font-size: 14px;
            }
        """)

        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)

        # 添加LOGO
        logo_label = QLabel(self)
        svg_renderer = QSvgRenderer('screen_logo.svg')
        pixmap = QPixmap(100, 100)  # 设置LOGO大小
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        svg_renderer.render(painter)
        painter.end()
        logo_label.setPixmap(pixmap)
        logo_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo_label)

        title_label = QLabel('Elite Screen Recorder', self)
        title_label.setFont(QFont('Segoe UI', 24, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # 添加音频设备选择
        self.audio_device_combo = ModernComboBox(self)
        self.audio_device_combo.addItems([d['name'] for d in sd.query_devices()])
        layout.addWidget(QLabel('Select Audio Device:'))
        layout.addWidget(self.audio_device_combo)

        # 添加音频测试按钮
        self.test_audio_btn = ModernButton('Test Audio', self)
        self.test_audio_btn.clicked.connect(self.test_audio)
        layout.addWidget(self.test_audio_btn)

        self.status_label = QLabel('Ready to record', self)
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.time_label = QLabel('Recording Time: 00:00:00', self)
        self.time_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.time_label)

        btn_layout = QHBoxLayout()
        self.start_btn = ModernButton('Start Recording', self)
        self.start_btn.clicked.connect(self.start_recording)
        btn_layout.addWidget(self.start_btn)

        self.stop_btn = ModernButton('Stop Recording', self)
        self.stop_btn.clicked.connect(self.stop_recording)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)

        layout.addLayout(btn_layout)

        self.audio_level_label = QLabel('Audio Level: 0 dB', self)
        self.audio_level_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.audio_level_label)

        self.audio_level_bar = QProgressBar(self)
        self.audio_level_bar.setRange(-60, 0)
        self.audio_level_bar.setTextVisible(False)
        self.audio_level_bar.setStyleSheet("""
            QProgressBar {
                background-color: #4a4a4a;
                border: none;
                border-radius: 5px;
                height: 10px;
            }
            QProgressBar::chunk {
                background-color: #1db954;
                border-radius: 5px;
            }
        """)
        layout.addWidget(self.audio_level_bar)

        self.format_combo = ModernComboBox(self)
        self.format_combo.addItems(['mp4', 'avi', 'mov'])
        layout.addWidget(self.format_combo)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 200)
        self.volume_slider.setValue(100)
        self.volume_slider.setTickPosition(QSlider.TicksBelow)
        self.volume_slider.setTickInterval(10)
        layout.addWidget(QLabel('Audio Volume:'))
        layout.addWidget(self.volume_slider)

        # 添加字幕开关
        self.subtitle_checkbox = QCheckBox('启用字幕', self)
        self.subtitle_checkbox.stateChanged.connect(self.toggle_subtitle)
        layout.addWidget(self.subtitle_checkbox)

        # 添加重新识别按钮
        self.rerecognize_btn = ModernButton('重新识别', self)
        self.rerecognize_btn.clicked.connect(self.rerecognize_audio)
        self.rerecognize_btn.setEnabled(True)  # 始终保启用状态
        layout.addWidget(self.rerecognize_btn)

        # 添加覆盖原文件的复选框
        self.overwrite_checkbox = QCheckBox('覆盖原文件', self)
        self.overwrite_checkbox.setChecked(True)  # 默认选中
        layout.addWidget(self.overwrite_checkbox)

        # 添加帧率选下拉框
        self.fps_combo = ModernComboBox(self)
        self.fps_combo.addItems(['24 fps', '30 fps', '60 fps'])
        self.fps_combo.setCurrentText('30 fps')  # 默认选择30fps
        self.fps_combo.currentTextChanged.connect(self.update_fps)
        layout.addWidget(QLabel('选择帧率:'))
        layout.addWidget(self.fps_combo)

        # 添加合并按钮
        self.merge_btn = ModernButton('合并视频和字幕', self)
        self.merge_btn.clicked.connect(self.merge_video_subtitle)
        layout.addWidget(self.merge_btn)

        # 添加启用摄像头的复选框
        self.camera_checkbox = QCheckBox('启用摄像头', self)
        self.camera_checkbox.stateChanged.connect(self.toggle_camera)
        layout.addWidget(self.camera_checkbox)

        self.setLayout(layout)

    def check_ffmpeg(self):
        try:
            subprocess.run(['ffmpeg', '-version'], check=True, capture_output=True, text=True)
            print("FFmpeg 可用")
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg 不可用: {e}")
            QMessageBox.critical(self, "错误", "FFmpeg 不可用。请确保 FFmpeg 安装并添加到系统路径中。")
        except FileNotFoundError:
            print("FFmpeg 未找到")
            QMessageBox.critical(self, "错误", "FFmpeg 未到。请确保 FFmpeg 已安装并添加到系统路径中。")

    def test_audio(self):
        device_index = self.audio_device_combo.currentIndex()
        self.test_audio_thread = threading.Thread(target=self.recorder.test_audio, args=(device_index,))
        self.test_audio_thread.start()
        self.audio_level_timer.start(100)
        self.test_audio_btn.setText("停止测试")
        self.test_audio_btn.clicked.disconnect()
        self.test_audio_btn.clicked.connect(self.stop_audio_test)

    def stop_audio_test(self):
        self.recorder.stop_audio_test()
        self.test_audio_thread.join()
        self.audio_level_timer.stop()
        self.test_audio_btn.setText("测试音")
        self.test_audio_btn.clicked.disconnect()
        self.test_audio_btn.clicked.connect(self.test_audio)

    def start_recording(self):
        # 在开始新的录制之前，确保重置所有状态
        self.reset_all_parameters()

        output_format = self.format_combo.currentText()
        output_file, _ = QFileDialog.getSaveFileName(self, "Save File", "", f"{output_format.upper()} Files (*.{output_format})")
        if output_file:
            if not output_file.lower().endswith(f'.{output_format}'):
                output_file += f'.{output_format}'
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.status_label.setText('Recording screen and audio...')
            
            device_index = self.audio_device_combo.currentIndex()
            device_info = sd.query_devices()
            if device_index >= 0 and device_index < len(device_info):
                device = device_info[device_index]
                print(f"Selected audio device: {device['name']}")
                if device['max_input_channels'] > 0:
                    volume = self.volume_slider.value() / 100
                    fps = int(self.fps_combo.currentText().split()[0])  # 获取选择的帧率
                    self.recorder.reset()  # 确保在开始新录制前重置录制器
                    self.recorder.video_fps = fps  # 设置选择的帧率
                    self.recorder.frame_duration = 1 / fps
                    self.recording_thread = threading.Thread(target=self.record_with_error_handling, 
                                                             args=(output_file, output_format, device_index, volume))
                    self.recording_thread.start()

                    self.audio_level_timer.start(100)
                    self.recording_time = 0
                    self.recording_timer.start(1000)
                    
                    # 显示录制图标
                    screen_geometry = QApplication.desktop().screenGeometry()
                    self.recording_icon.move(screen_geometry.width() - 120, 20)
                    self.recording_icon.is_paused = False
                    self.recording_icon.is_stopping = False
                    self.recording_icon.show()
                else:
                    self.status_label.setText('Selected device does not support audio input')
            else:
                self.status_label.setText('Invalid audio device selected')

            self.hide()  # 隐藏UI界面
            # QApplication.instance().installEventFilter(self)  # 确保件过滤器在录制开始时被安装

            self.output_file = output_file  # 保存输出文件路径

            if self.camera_checkbox.isChecked():
                self.recorder.start_camera()
                self.camera_preview_window.show()
                self.camera_preview_window.move_to_bottom_right()
                self.camera_timer.start(33)

    def record_with_error_handling(self, output_file, output_format, device_index, volume):
        try:
            logging.info(f"Starting recording to file: {output_file}")
            logging.info(f"Audio device index: {device_index}")
            logging.info(f"Audio volume: {volume}")
            self.recorder.record_screen(output_file, True, output_format, device_index, volume)
        except Exception as e:
            logging.error(f"Error during recording: {e}", exc_info=True)
            self.recording_failed.emit(f'Recording failed: {str(e)}')
        finally:
            logging.info("Recording ended")
            self.recording_stopped.emit()

    def on_recording_stopped(self):
        time.sleep(0.5)
        self.reset_recording_state()
        self.show()  # 显示主UI界面
        self.rerecognize_btn.setEnabled(True)  # 确保在录制停止后启用重新识别按钮

    def reset_recording_state(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText('Ready to record')
        self.recording_icon.hide()

        self.audio_level_timer.stop()
        self.recording_timer.stop()
        self.audio_level_bar.setValue(-60)
        self.audio_level_label.setText('Audio Level: -60 dB')
        self.time_label.setText('Recording Time: 00:00:00')

        self.recording_time = 0
        self.recorder.reset()
        self.recording_thread = None

    def on_recording_failed(self, message):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(message)
        self.recording_icon.hide()
        self.audio_level_timer.stop()
        self.recording_timer.stop()
        self.audio_level_bar.setValue(-60)
        self.audio_level_label.setText('Audio Level: -60 dB')

    def update_audio_level(self):
        level = self.recorder.get_audio_level()
        if level > 0:
            db_level = 20 * math.log10(level)
        else:
            db_level = -60
        db_level = max(-60, min(db_level, 0))
        self.audio_level_bar.setValue(int(db_level))
        self.audio_level_label.setText(f'Audio Level: {db_level:.1f} dB')
        if hasattr(self, 'recording_icon'):
            self.recording_icon.set_audio_level(level)

    def update_recording_time(self):
        self.recording_time += 1
        hours = self.recording_time // 3600
        minutes = (self.recording_time % 3600) // 60
        seconds = self.recording_time % 60
        self.time_label.setText(f'Recording Time: {hours:02d}:{minutes:02d}:{seconds:02d}')

    def toggle_pause_recording(self):
        if self.recorder.recording:
            self.recorder.toggle_pause()
            self.recording_icon.toggle_pause()
            if self.recorder.is_paused:
                self.status_label.setText('Recording paused')
                self.recording_timer.stop()
            else:
                self.status_label.setText('Recording resumed')
                self.recording_timer.start()

    def stop_recording(self):
        self.recorder.stop_recording()
        self.recording_icon.start_stop_animation()
        if self.recording_thread:
            self.recording_thread.join()
        self.export_video()
        # QApplication.instance().removeEventFilter(self)  # 在录制停止时移除事件过滤器

        if self.camera_checkbox.isChecked():
            self.recorder.stop_camera()
            self.camera_preview_window.hide()
            self.camera_timer.stop()

    def export_video(self):
        self.status_label.setText('正在处理视频...')
        QApplication.processEvents()  # 确保UI更新

        if self.subtitle_enabled:
            self.status_label.setText('正在生成字幕...')
            QApplication.processEvents()  # 确保UI更新
            try:
                base_name = os.path.splitext(self.output_file)[0]
                self.output_file_with_subtitles = f"{base_name}_with_subtitles.mp4"
                self.srt_file = f"{base_name}.srt"
                
                # 使用绝对路径
                video_path = os.path.abspath(self.output_file)
                output_path = os.path.abspath(self.output_file_with_subtitles)
                srt_path = os.path.abspath(self.srt_file)
                
                original_video, srt_file, subtitled_video = process_video_with_subtitles(
                    video_path,  # 原始视频路径
                    output_path,  # 输出视频路径
                    srt_path  # SRT 文件路径
                )
                
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Information)
                msg.setText("字幕生成完成")
                msg.setInformativeText(f"原始视频: {original_video}\n"
                                       f"字幕文件: {srt_file}\n"
                                       f"带字幕的视频: {subtitled_video}")
                msg.setWindowTitle("导出成功")
                msg.exec_()
                
                self.status_label.setText('字幕生成完成，所有文件已成功导出。')
            except Exception as e:
                error_msg = QMessageBox()
                error_msg.setIcon(QMessageBox.Critical)
                error_msg.setText("字幕生成失败")
                error_msg.setInformativeText(f"错误信息: {str(e)}")
                error_msg.setDetailedText(f"详细错误信息:\n{traceback.format_exc()}")
                error_msg.setWindowTitle("导出错误")
                error_msg.exec_()
                
                self.status_label.setText(f'字幕生成失败: {str(e)}')
        else:
            self.status_label.setText('视频已成功导出。')

        # 无论是否启用字幕，都确保重新识别按钮可用
        self.rerecognize_btn.setEnabled(True)

        self.reset_all_parameters()
        self.status_label.setText('视频导出成功。准备开始新的录制。')

    def rerecognize_audio(self):
        audio_file, _ = QFileDialog.getOpenFileName(self, "选择音频文件", "", "音频文件 (*.wav *.mp3)")
        if audio_file:
            self.status_label.setText('正在重新识别音频...')
            try:
                service = OpenAITranscriptionService()
                transcript = service.transcribe_audio(audio_file)
                if transcript and 'segments' in transcript:
                    srt_content = service.generate_srt_subtitles(transcript)
                    
                    # 生成新的 SRT 文件
                    base_name = os.path.splitext(audio_file)[0]
                    srt_file = f"{base_name}_subtitles.srt"

                    with open(srt_file, "w", encoding="utf-8") as f:
                        f.write(srt_content)
                    
                    msg = QMessageBox()
                    msg.setIcon(QMessageBox.Information)
                    msg.setText("重新识别完成")
                    msg.setInformativeText(f"字幕文件已生成: {srt_file}")
                    msg.setWindowTitle("重新识别成功")
                    msg.exec_()
                    
                    self.status_label.setText('重新识别完成，字幕文件已生成。')
                else:
                    raise ValueError("转录结果无效或缺少段落息")
            except Exception as e:
                error_msg = QMessageBox()
                error_msg.setIcon(QMessageBox.Critical)
                error_msg.setText("重新识别失败")
                error_msg.setInformativeText(f"错误信息: {str(e)}")
                error_msg.setDetailedText(f"详错误信息:\n{traceback.format_exc()}")
                error_msg.setWindowTitle("重新识别错误")
                error_msg.exec_()
                
                self.status_label.setText(f'重新识别失败: {str(e)}')
        else:
            self.status_label.setText('未选择音频文件，重新识别取消。')

    def reset_all_parameters(self):
        self.reset_recording_state()
        self.recorder.reset()
        self.recording_icon.hide()
        self.recording_time = 0
        self.time_label.setText('Recording Time: 00:00:00')
        self.audio_level_bar.setValue(-60)
        self.audio_level_label.setText('Audio Level: -60 dB')
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.show()  # 显示主UI界面

    def start_area_selection(self):
        if self.recorder.recording and not self.recorder.is_paused:
            print("Starting area selection...")  # 添加调试输出
            self.hide()  # 隐藏主UI
            self.area_selection_widget = AreaSelectionWidget(self)
            self.area_selection_widget.area_selected.connect(self.on_area_selected)
            self.area_selection_widget.showFullScreen()
            self.recording_icon.raise_()  # 确保录制图标在最顶层
        else:
            print("Recording is not active or is paused. Cannot select area.")

    def on_area_selected(self, rect):
        self.selected_area = rect
        self.recorder.set_recording_area(rect)
        self.area_selection_widget.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_R and event.modifiers() == Qt.ControlModifier:
            if self.recorder.recording and not self.recorder.is_paused:
                self.start_area_selection()
            event.accept()
        else:
            super().keyPressEvent(event)

    def toggle_subtitle(self, state):
        self.subtitle_enabled = state == Qt.Checked

    def update_fps(self, fps_text):
        fps = int(fps_text.split()[0])
        self.recorder.video_fps = fps
        self.recorder.frame_duration = 1 / fps
        print(f"帧率已更新为: {fps} fps")

    def merge_video_subtitle(self):
        video_file, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "视频文件 (*.mp4 *.avi *.mov)")
        if not video_file:
            return

        srt_file, _ = QFileDialog.getOpenFileName(self, "选择字幕文件", "", "字幕文件 (*.srt)")
        if not srt_file:
            return

        output_file, _ = QFileDialog.getSaveFileName(self, "保存合并后的视频", "", "视频文件 (*.mp4)")
        if not output_file:
            return

        try:
            self.status_label.setText('正在合并视频和字幕...')
            QApplication.processEvents()  # 更新UI

            original_video, srt_file, subtitled_video = process_video_with_subtitles(
                video_file,
                output_file,
                srt_file
            )

            msg = QMessageBox()
            msg.setIcon(QMessageBox.Information)
            msg.setText("视频和字幕合并完成")
            msg.setInformativeText(f"原始视频: {original_video}\n"
                                   f"字幕文件: {srt_file}\n"
                                   f"带字幕的视频: {subtitled_video}")
            msg.setWindowTitle("合并成功")
            msg.exec_()

            self.status_label.setText('视频和字幕合并完成。')
        except Exception as e:
            error_msg = QMessageBox()
            error_msg.setIcon(QMessageBox.Critical)
            error_msg.setText("合并失败")
            error_msg.setInformativeText(f"错误信息: {str(e)}")
            error_msg.setDetailedText(f"详细错误信息:\n{traceback.format_exc()}")
            error_msg.setWindowTitle("合并错误")
            error_msg.exec_()

            self.status_label.setText(f'合并失败: {str(e)}')

    def toggle_camera(self, state):
        if state == Qt.Checked:
            self.recorder.start_camera()
            self.camera_preview_window.show()
            self.camera_preview_window.move_to_bottom_right()
            self.camera_timer.start(33)
        else:
            self.stop_camera()
            self.camera_preview_window.hide()
            self.camera_timer.stop()

    def update_camera_preview(self):
        try:
            frame = self.recorder.get_camera_frame()
            if frame is not None:
                self.camera_preview_window.update_preview(frame)
            else:
                logging.warning("Camera frame is None")
        except Exception as e:
            logging.error(f"Error updating camera preview: {e}")

    def stop_camera(self):
        self.recorder.stop_camera()
        self.camera_checkbox.setChecked(False)
        self.camera_timer.stop()

def process_video_with_subtitles(video_path, output_path, srt_path):
    try:
        # 检查原始视频文件是否存在
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"原始视频文件不存在: {video_path}")

        # 检查 SRT 文件是否存在，如果不存在则尝试生成
        if not os.path.exists(srt_path):
            print(f"警告: SRT 文件不存在: {srt_path}")
            print("将尝试生成 SRT 文件...")
            
            # 这里添加生成 SRT 文件的代码
            service = OpenAITranscriptionService()
            transcript = service.transcribe_audio(video_path)
            if transcript and 'segments' in transcript:
                srt_content = service.generate_srt_subtitles(transcript)
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
                print(f"SRT 文件已生成: {srt_path}")
            else:
                raise ValueError("无法生成 SRT 文件")

        # 再次检查 SRT 文件是否存在
        if not os.path.exists(srt_path):
            raise FileNotFoundError(f"SRT 文件生成失败: {srt_path}")

        # 检查原始视频是否包含音频流
        probe = ffmpeg.probe(video_path)
        audio_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), None)
        
        if audio_stream is None:
            print("警告：原始视频不包含音频流")

        # 使用 FFmpeg 添加字幕
        try:
            subtitle_style = (
                'FontName=SimHei,'
                'FontSize=15,'
                'PrimaryColour=&H00FFFFFF,'  # 白色
                'OutlineColour=&H000000,'  # 纯黑色轮廓
                'BackColour=&H80000000,'     # 半透明背景
                'Bold=1,'
                'Shadow=0,'
                'Alignment=2'                # 底部居中
            )
            
            input_video = ffmpeg.input(video_path)
            
            # 如果有音频流，则复制音频；否则不处理音频
            if audio_stream:
                audio = input_video.audio
            else:
                audio = None
            
            video = (
                input_video
                .filter('subtitles', filename=srt_path, force_style=subtitle_style)
            )
            
            output = ffmpeg.output(video, audio, output_path, vcodec='libx264', acodec='aac' if audio_stream else None)
            output = output.overwrite_output()
            
            ffmpeg.run(output, capture_stdout=True, capture_stderr=True)
            
        except ffmpeg.Error as e:
            logging.error(f"FFmpeg 错误:\nSTDOUT:\n{e.stdout.decode('utf8')}\nSTDERR:\n{e.stderr.decode('utf8')}")
            raise

        logging.info("视频处理成功完成")
        return video_path, srt_path, output_path

    except Exception as e:
        logging.error(f"处理视频时发生错误: {str(e)}")
        logging.error(f"详细错误信息: {traceback.format_exc()}")
        raise

if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        app.setStyle(QStyleFactory.create('Fusion'))
        ex = ScreenRecorderUI()
        ex.show()
        sys.exit(app.exec_())
    except Exception as e:
        logging.exception("An error occurred in the main application")
        QMessageBox.critical(None, "Critical Error", f"An unexpected error occurred:\n\n{str(e)}\n\nPlease check the log file for more details.")