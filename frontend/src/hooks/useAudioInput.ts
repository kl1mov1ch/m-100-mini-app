import { App } from 'antd';
import { useRef, useState } from 'react';
import { request } from '../lib/api';

export function useAudioInput(project: string, onTranscript: (text: string) => void) {
	const { message } = App.useApp();
	const [recording, setRecording] = useState(false);
	const [transcribing, setTranscribing] = useState(false);
	const recorder = useRef<MediaRecorder | null>(null);
	const microphoneStream = useRef<MediaStream | null>(null);
	const audioChunks = useRef<Blob[]>([]);
	const recordingTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
	const stop = () => {
		if (recorder.current?.state === 'recording') recorder.current.stop();
		if (recordingTimeout.current) clearTimeout(recordingTimeout.current);
		microphoneStream.current?.getTracks().forEach((track) => track.stop());
		setRecording(false);
	};
	const uploadAudio = async (file: File) => {
		setTranscribing(true);
		try {
			const payload = new FormData();
			payload.append('file', file);
			const response = await request<{ text: string }>('/transcribe', payload, project);
			onTranscript(response.text);
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setTranscribing(false);
		}
		return false;
	};
	const toggleRecording = async () => {
		if (recording) {
			stop();
			return;
		}
		if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
			message.info('Запись недоступна в этом браузере. Добавьте готовое голосовое сообщение.');
			return;
		}
		try {
			const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			microphoneStream.current = stream;
			audioChunks.current = [];
			const mediaRecorder = new MediaRecorder(stream);
			recorder.current = mediaRecorder;
			mediaRecorder.ondataavailable = (event) => {
				if (event.data.size) audioChunks.current.push(event.data);
			};
			mediaRecorder.onstop = () => {
				const recordingBlob = new Blob(audioChunks.current, {
					type: mediaRecorder.mimeType,
				});
				stream.getTracks().forEach((track) => track.stop());
				setRecording(false);
				if (recordingBlob.size)
					void uploadAudio(
						new File([recordingBlob], 'voice.webm', {
							type: mediaRecorder.mimeType,
						}),
					);
			};
			mediaRecorder.start();
			setRecording(true);
			recordingTimeout.current = setTimeout(stop, 300000);
		} catch {
			message.info('Разрешите доступ к микрофону или добавьте голосовое сообщение файлом.');
		}
	};
	return { recording, transcribing, toggleRecording, uploadAudio, stop };
}
