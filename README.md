<<<<<<< HEAD
# Elite Screen Recorder

Elite Screen Recorder 是一个高性能的屏幕录制工具，专为专业用户设计。它提供了简洁而强大的用户界面，支持高质量的屏幕和音频录制。

## 功能特点

- 高性能屏幕捕获，支持高帧率录制
- 多种音频输入设备选择
- 实时音频电平监测
- 支持多种输出格式（mp4, avi, mov）
- 优雅的录制状态指示器
- 音频设备测试功能

## 系统要求

- Windows 10 或更高版本
- Python 3.7+

## 安装

1. 克隆仓库：

   ```bash
   git clone https://github.com/yourusername/elite-screen-recorder.git
   cd elite-screen-recorder
   ```

2. 创建并激活虚拟环境（可选但推荐）：

   ```bash
   python -m venv venv
   source venv/bin/activate  # 在 Windows 上使用 venv\Scripts\activate
   ```

3. 安装依赖：

   ```bash
   pip install PyQt5 numpy opencv-python sounddevice soundfile d3dshot mss ffmpeg-python
   ```

4. 安装 FFmpeg：
   - Windows: 下载 FFmpeg 并将其添加到系统路径
   - macOS: `brew install ffmpeg`
   - Linux: `sudo apt-get install ffmpeg`

## 使用方法

1. 运行程序：

   ```bash
   python record_screen/screen_recorder_ui.py
   ```

2. 在界面上选择音频输入设备。

3. 使用"Test Audio"按钮测试音频输入。

4. 选择输出格式（mp4, avi, mov）。

5. 点击"Start Recording"开始录制。

6. 录制过程中，屏幕右上角会显示一个优雅的录制状态指示器。

7. 完成后，点击"Stop Recording"结束录制。

8. 选择保存位置，文件将被保存为选定的格式。

## 注意事项

- 确保给予应用程序适当的屏幕录制权限。
- 高质量录制可能需要较大的存储空间。
- 录制性能可能会受到系统配置的影响。

## 贡献

欢迎提交问题和拉取请求。对于重大更改，请先开issue讨论您想要改变的内容。

## 许可

[MIT](https://choosealicense.com/licenses/mit/)
=======
# screen_shot
>>>>>>> a56aea0bae34348f5d038fcd822c2fae186bc610
