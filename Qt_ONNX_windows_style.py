from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QTextEdit, QCheckBox
from PyQt5.QtGui import QMouseEvent, QIcon
from PyQt5.QtCore import QProcess, Qt, QEvent, QTimer, pyqtSignal
from funasr_onnx import Paraformer
from pynput import keyboard
from pynput.keyboard import Controller, Key
import threading
from opencc import OpenCC
import sounddevice as sd
import numpy as np
import soundfile as sf
import os

class MyButton(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.isPressed = False
        self.pressed.connect(self.change_color)
        self.released.connect(self.restore_color)
        self.setCursor(Qt.PointingHandCursor)

    def change_color(self):
        self.setStyleSheet("background-color: rgba(90, 133, 15, 0.8);")  # Change to red when pressed

    def restore_color(self):
        if self.underMouse():
            self.setStyleSheet("background-color: rgba(100, 145, 40, 1);")  # Change to hover color if mouse is still over the button
        else:
            self.setStyleSheet("background-color: rgba(90, 133, 15, 1);")  # Restore to original color when released

    def enterEvent(self, event):
        self.setStyleSheet("background-color: rgba(100, 145, 40, 1);")  # Change to blue when mouse enters

    def leaveEvent(self, event):
        self.restore_color()  # Restore to original color when mouse leaves

    def simulatePress(self):
        if not self.isPressed:
            pressEvent = QMouseEvent(QEvent.MouseButtonPress, self.rect().center(), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            QApplication.postEvent(self, pressEvent)
            self.isPressed = True

    def simulateRelease(self):
        if self.isPressed:
            releaseEvent = QMouseEvent(QEvent.MouseButtonRelease, self.rect().center(), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            QApplication.postEvent(self, releaseEvent)
            self.isPressed = False

class MyWindow(QWidget):
    # Define a signal
    transcription_ready = pyqtSignal(str)
    text_ready = pyqtSignal(str)  # Define a new signal
    def __init__(self):
        super().__init__()

        # 设置窗口的透明度
        self.setWindowOpacity(0.8)

        # 设置全局热键
        # self.global_hotkey = keyboard.Key.scroll_lock
        # self.global_hotkey = keyboard.Key.shift_r  # 波浪号键（反引号键 ` ）
        self.global_hotkey = keyboard.Key.caps_lock  # 波浪号键（反引号键 ` ）
        # self.global_hotkey = keyboard.KeyCode.from_char('')   # 波浪号键（反引号键 ` ）
        # Connect the signal to a slot
        self.transcription_ready.connect(self.update_transcription)

        # Connect the signal to a slot
        self.text_ready.connect(self.update_text)

        # 窗口置顶
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        # 设置窗口图标
        self.setWindowIcon(QIcon('./icon.png'))

        # 设置窗口的标题
        self.setWindowTitle('RTX-IM')

        # 设置窗口的大小
        self.resize(200, 100)

        # 在窗口中间添加一个按钮，大小是窗口宽度的一半
        self.button = MyButton(self)
        self.button.setText("长按输入")
        self.button.resize(self.width() // 2, 32)

        # 添加一个新的按钮，位置在窗口宽度的一半，大小也是窗口宽度的一半
        self.convertButton = MyButton(self)
        self.convertButton.setText("繁简转换")
        self.convertButton.resize(self.width() // 2, 32)
        self.convertButton.move(self.width() // 2, int(self.height() - self.convertButton.height()))
        self.convertButton.released.connect(self.convertText)


        # 添加一个文本编辑框
        self.textEdit = QTextEdit(self)
        self.textEdit.move(0, 0)
        self.textEdit.resize(self.width(), self.height() - self.button.height())

        # # 设置文本编辑框的背景颜色为半透明的黑色，文本颜色为白色
        # self.textEdit.setStyleSheet("background-color: rgba(0, 0, 0, 128); color: white;")

        # 使按钮居中
        self.button.move(int((self.width() - self.button.width()) / 2), int(self.height() - self.button.height()))

        # 创建一个进程对象用于录音
        self.recorder = QProcess()

        # 初始化模型
        # model_dir = "./speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        model_dir = r"C:\Users\andIre222394ooo\.cache\modelscope\hub\iic\speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        self.model = Paraformer(model_dir, batch_size=1, quantize=True)

        # 预热模型，避免第一次推理时的延迟
        self.model(['./warmup.wav'])

        # 当按钮被按下时开始录音
        self.button.pressed.connect(self.startRecording)
        self.button.released.connect(self.stopRecording)

        # Setup global hotkey
        self.setup_hotkey()

        self.timer = QTimer()
        self.timer.timeout.connect(self.simulatePress)

        # Initialize dragPosition attribute
        self.dragPosition = None

        # Initialize a lock for the convertTextThread
        self.convert_lock = threading.Lock()

        # 添加一个定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.simulatePress)

        # Initialize OpenCC
        self.cc_s2t = OpenCC('s2twp')
        self.cc_t2s = OpenCC('t2s')

        # 打开并读取文件
        with open('library.txt', 'r', encoding='utf-8') as f:
            library_text = f.read()

        # 将读取的内容转换为一个集合
        self.traditional_chars = set(library_text)

        # 添加保存录音文件的复选框
        self.save_audio_checkbox = QCheckBox("保存录音", self)
        self.save_audio_checkbox.setChecked(False)  # 默认不保存
        self.save_audio_checkbox.move(10, 10)  # 设置位置

    def convertText(self):
        # 创建一个新的线程来处理转换操作
        thread = threading.Thread(target=self.convertTextThread)
        thread.start()

    def convertTextThread(self):
        # Acquire the lock before starting the conversion
        self.convert_lock.acquire()
        try:
            text = self.textEdit.toPlainText()
            if any(char in self.traditional_chars for char in text):
                converted = self.cc_t2s.convert(text)
            else:
                converted = self.cc_s2t.convert(text)
            self.text_ready.emit(converted)  # Emit the signal with the converted text

            # 将转换后的文本复制到剪贴板
            clipboard = QApplication.clipboard()
            clipboard.setText(converted)
            print("Text converted")
        finally:
            # Release the lock after the conversion is done
            self.convert_lock.release()

    def update_text(self, text):
        self.textEdit.setText(text)  # Update the textEdit in the main thread

    def setup_hotkey(self):
        def on_press(key):
            try:
                if key == self.global_hotkey and not self.button.isPressed:
                    self.button.simulatePress()
            except AttributeError:
                pass

        def on_release(key):
            if key == self.global_hotkey and self.button.isPressed:
                self.button.simulateRelease()

        # Collect events until released
        self.listener = keyboard.Listener(
            on_press=on_press,
            on_release=on_release)
        self.listener.start()

        # 修改录音参数
        # self.fs = 16000  # 采样率改为16kHz
        # self.channels = 1  # 通道数改为1（单声道）
        self.fs = 44100  # Sample rate
        self.channels = 1  # Number of channels


        # 创建一个用于存储录音数据的列表
        self.myrecording = []

        # 创建一个录音流
        self.stream = sd.InputStream(samplerate=self.fs, channels=self.channels, callback=self.audio_callback)
        self.myrecording = []
        self.isRecording = False
        self.stream.start()
        print("Recording started...")

    def startRecording(self):
        # 清空录音数据
        self.myrecording = []
        self.isRecording = True  # 开始录音，改变状态变量的值

    def stopRecording(self):
        self.isRecording = False  # 录音结束，改变状态变量的值
        # 将录音数据转换为numpy数组
        myrecording_np = np.array(self.myrecording)
        
        # 创建临时文件用于转录
        temp_wav = 'temp.wav'
        sf.write(temp_wav, myrecording_np, self.fs)
        
        # 如果用户选择保存录音，则另存一份
        if self.save_audio_checkbox.isChecked():
            sf.write('audio.wav', myrecording_np, self.fs)
        
        # 开始转录音频
        self.transcribe_audio(temp_wav)
        
        # 清理内存
        self.myrecording = []

    def audio_callback(self, indata, frames, time, status):
        # 如果正在录音，就将录音数据添加到列表中
        if self.isRecording:
            self.myrecording.extend(indata.tolist())

    def simulatePress(self):
        if not self.button.isPressed and not self.isRecording:  # 在模拟鼠标按下事件时，检查是否正在录音
            self.button.simulatePress()

    def simulateRelease(self):
        if self.button.isPressed and not self.isRecording:  # 在模拟鼠标释放事件时，检查是否正在录音
            self.button.simulateRelease()

    def transcribe_audio(self, wav_file):
        # 创建一个新的线程来执行转录的任务
        thread = threading.Thread(target=self.transcribe_audio_thread, args=(wav_file,))
        thread.start()

    def transcribe_audio_thread(self, wav_file):
        try:
            result = self.model([wav_file])
            print("Transcription: ", result)
            if result and 'preds' in result[0]:
                transcription = result[0]['preds'][0]
                # Emit the signal with the transcription
                self.transcription_ready.emit(transcription)
        finally:
            # 转录完成后删除临时文件
            if os.path.exists(wav_file) and wav_file == 'temp.wav':
                os.remove(wav_file)

    def update_transcription(self, transcription):
        self.textEdit.setText(transcription)
        # 将文本复制到剪贴板
        clipboard = QApplication.clipboard()
        clipboard.setText(transcription)

        # 模拟按下Ctrl+V
        keyboard = Controller()
        with keyboard.pressed(Key.ctrl):  # 直接使用Key.ctrl
            keyboard.press('v')
            keyboard.release('v')

    # 让窗口可以拖拽
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragPosition = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragPosition is not None:
            self.move(event.globalPos() - self.dragPosition)
            event.accept()

    # 让布局自适应大小
    def resizeEvent(self, event):
        # 让文本编辑框的大小自适应窗口大小
        self.textEdit.resize(self.width(), self.height() - self.button.height())
        # 让两个按钮的宽度自适应窗口大小，高度保持不变
        self.button.resize(self.width() // 2, self.button.height())
        self.convertButton.resize(self.width() // 2, self.convertButton.height())
        # 让输入按钮靠左，转换按钮靠右
        self.button.move(0, int(self.height() - self.button.height()))
        self.convertButton.move(self.width() // 2, int(self.height() - self.convertButton.height()))

if __name__ == "__main__":
    app = QApplication([])
    window = MyWindow()
    window.show()

    # Load and apply the stylesheet
    with open('style.css', 'r') as f:
        app.setStyleSheet(f.read())

    app.exec_()