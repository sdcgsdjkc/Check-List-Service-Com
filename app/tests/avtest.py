import math
import struct

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QTimer
from PyQt6.QtMultimedia import (QAudioFormat, QAudioSink, QAudioSource, QCamera,
                                QMediaCaptureSession, QMediaDevices)
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from app.tests.base import BaseTestPage

SAMPLE_RATE = 44100
TONE_SECONDS = 0.8
TONE_HZ = 440.0


class AvPage(BaseTestPage):
    title = "Камера, микрофон и динамики"
    hint = "Проверьте картинку с камеры, шкалу микрофона и нажмите кнопки теста динамиков («Тест Л» / «Тест П»)."

    def build_body(self):
        row = QHBoxLayout()
        camera_column = QVBoxLayout()
        self.video = QVideoWidget()
        self.video.setMinimumSize(420, 280)
        self.cam_status = QLabel("Камера: —")
        camera_column.addWidget(self.video, 1)
        camera_column.addWidget(self.cam_status)
        side = QVBoxLayout()
        side.addWidget(QLabel("Уровень микрофона:"))
        self.mic_bar = QProgressBar()
        self.mic_bar.setRange(0, 100)
        self.mic_bar.setTextVisible(False)
        side.addWidget(self.mic_bar)
        self.mic_status = QLabel("Микрофон: —")
        side.addWidget(self.mic_status)
        side.addSpacing(18)
        side.addWidget(QLabel("Динамики:"))
        speaker_row = QHBoxLayout()
        self.left_button = QPushButton("Тест Л (левый)")
        self.right_button = QPushButton("Тест П (правый)")
        self.left_button.clicked.connect(lambda: self.play_tone(0))
        self.right_button.clicked.connect(lambda: self.play_tone(1))
        speaker_row.addWidget(self.left_button)
        speaker_row.addWidget(self.right_button)
        side.addLayout(speaker_row)
        side.addStretch(1)
        row.addLayout(camera_column, 3)
        row.addLayout(side, 2)
        self.body.addLayout(row, 1)
        self.session = QMediaCaptureSession()
        self.camera = None
        self.audio_source = None
        self.audio_io = None
        self.mic_format = None
        self.sink = None
        self.tone_buffer = None
        self.mic_timer = QTimer(self)
        self.mic_timer.timeout.connect(self.read_mic)

    def on_enter(self):
        camera_device = QMediaDevices.defaultVideoInput()
        if camera_device.isNull():
            self.cam_status.setText("Камера: не обнаружена")
        else:
            self.camera = QCamera(camera_device)
            self.session.setCamera(self.camera)
            self.session.setVideoOutput(self.video)
            self.camera.start()
            self.cam_status.setText(f"Камера: {camera_device.description()}")
        mic_device = QMediaDevices.defaultAudioInput()
        if mic_device.isNull():
            self.mic_status.setText("Микрофон: не обнаружен")
        else:
            audio_format = QAudioFormat()
            audio_format.setSampleRate(16000)
            audio_format.setChannelCount(1)
            audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not mic_device.isFormatSupported(audio_format):
                audio_format = mic_device.preferredFormat()
            self.mic_format = audio_format.sampleFormat()
            self.audio_source = QAudioSource(mic_device, audio_format)
            self.audio_io = self.audio_source.start()
            self.mic_status.setText(f"Микрофон: {mic_device.description()}")
            self.mic_timer.start(60)
        self.set_status("проверьте камеру, микрофон и оба динамика")

    def read_mic(self):
        if self.audio_io is None:
            return
        raw = bytes(self.audio_io.readAll())
        if len(raw) < 4:
            return
        if self.mic_format == QAudioFormat.SampleFormat.Int16:
            count = len(raw) // 2
            samples = struct.unpack(f"<{count}h", raw[:count * 2])
            peak = max(abs(s) for s in samples) / 32767.0
        elif self.mic_format == QAudioFormat.SampleFormat.Float:
            count = len(raw) // 4
            samples = struct.unpack(f"<{count}f", raw[:count * 4])
            peak = min(1.0, max(abs(s) for s in samples))
        else:
            peak = max(raw) / 255.0
        self.mic_bar.setValue(int(peak * 100))

    def play_tone(self, channel):
        audio_format = QAudioFormat()
        audio_format.setSampleRate(SAMPLE_RATE)
        audio_format.setChannelCount(2)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            self.set_status("устройство вывода звука не найдено", False)
            return
        frames = int(SAMPLE_RATE * TONE_SECONDS)
        data = bytearray()
        for i in range(frames):
            fade = min(1.0, i / 2000.0, (frames - i) / 2000.0)
            value = int(14000 * fade * math.sin(2 * math.pi * TONE_HZ * i / SAMPLE_RATE))
            data += struct.pack("<hh", value if channel == 0 else 0, value if channel == 1 else 0)
        if self.sink is not None:
            self.sink.stop()
        self.tone_buffer = QBuffer(self)
        self.tone_buffer.setData(QByteArray(bytes(data)))
        self.tone_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.sink = QAudioSink(device, audio_format)
        self.sink.start(self.tone_buffer)

    def on_leave(self):
        self.mic_timer.stop()
        if self.camera is not None:
            self.camera.stop()
            self.camera = None
        if self.audio_source is not None:
            self.audio_source.stop()
            self.audio_source = None
            self.audio_io = None
        if self.sink is not None:
            self.sink.stop()
            self.sink = None
