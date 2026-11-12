import { App } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { request } from '../lib/api';
import type { SpeechEngine } from '../types';

type AudioActivity = 'idle' | 'opening' | 'listening' | 'recording' | 'finishing' | 'transcribing';

const appendTranscript = (text: string, transcript: string) =>
	[text.trimEnd(), transcript.trim()].filter(Boolean).join('\n').slice(0, 8000);

export function useAudioInput(
	project: string,
	scope: string,
	text: string,
	onTextChange: (text: string) => void,
) {
	const { message } = App.useApp();
	const [activity, setActivity] = useState<AudioActivity>('idle');
	const [useRecording, setUseRecording] = useState(false);
	const operation = useRef<AbortController | null>(null);
	const finishRecording = useRef<(() => void) | null>(null);
	const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
	const live = !!Recognition && !useRecording;
	const recording = activity === 'listening' || activity === 'recording';
	const pending = activity !== 'idle' && !recording;
	const cancel = () => {
		operation.current?.abort();
		operation.current = null;
		finishRecording.current = null;
		setActivity('idle');
	};
	useEffect(() => {
		setActivity('idle');
		return () => {
			operation.current?.abort();
			operation.current = null;
			finishRecording.current = null;
		};
	}, [project, scope]);

	const finish = (controller: AbortController) => {
		if (operation.current !== controller) return;
		operation.current = null;
		finishRecording.current = null;
		setActivity('idle');
	};

	const transcribe = async (file: File, controller: AbortController) => {
		setActivity('transcribing');
		try {
			const payload = new FormData();
			payload.append('file', file);
			const response = await request<{ text: string }>(
				'/transcribe',
				payload,
				project,
				controller.signal,
			);
			if (!controller.signal.aborted) onTextChange(appendTranscript(text, response.text));
		} catch (error) {
			if (!controller.signal.aborted) message.error((error as Error).message);
		} finally {
			finish(controller);
		}
	};

	const uploadAudio = (file: File) => {
		if (operation.current) return false;
		const controller = new AbortController();
		operation.current = controller;
		void transcribe(file, controller);
		return false;
	};

	const startLive = (engine: SpeechEngine, controller: AbortController) => {
		engine.lang = 'ru-RU';
		engine.continuous = true;
		engine.interimResults = true;
		engine.onresult = ({ results }) => {
			if (controller.signal.aborted) return;
			const transcript = Array.from(results, (result) => result[0].transcript.trim())
				.filter(Boolean)
				.join(' ');
			onTextChange(transcript ? appendTranscript(text, transcript) : text);
		};
		engine.onerror = ({ error }) => {
			if (controller.signal.aborted) return;
			if (error === 'no-speech') {
				message.info('Речь не распознана. Попробуйте ещё раз.');
			} else if (error === 'not-allowed' || error === 'audio-capture') {
				message.warning('Проверьте доступ к микрофону в браузере.');
			} else {
				setUseRecording(true);
				message.info('Диктовка недоступна. Нажмите микрофон ещё раз для записи.');
			}
		};
		const timeout = setTimeout(() => finishRecording.current?.(), 300000);
		engine.onend = () => {
			clearTimeout(timeout);
			finish(controller);
		};
		finishRecording.current = () => {
			setActivity('finishing');
			engine.stop();
		};
		controller.signal.addEventListener(
			'abort',
			() => {
				clearTimeout(timeout);
				engine.abort();
			},
			{ once: true },
		);
		try {
			engine.start();
			setActivity('listening');
		} catch {
			cancel();
			setUseRecording(true);
			message.info('Диктовка недоступна. Нажмите микрофон ещё раз для записи.');
		}
	};

	const startRecording = async (controller: AbortController) => {
		if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
			message.info('Микрофон недоступен. Вставьте текст или загрузите голосовое сообщение.');
			finish(controller);
			return;
		}
		setActivity('opening');
		try {
			const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			const release = () => stream.getTracks().forEach((track) => track.stop());
			if (controller.signal.aborted) {
				release();
				return;
			}
			controller.signal.addEventListener('abort', release, { once: true });
			const recorder = new MediaRecorder(stream);
			const chunks: Blob[] = [];
			recorder.ondataavailable = (event) => {
				if (event.data.size) chunks.push(event.data);
			};
			const timeout = setTimeout(() => finishRecording.current?.(), 300000);
			controller.signal.addEventListener('abort', () => clearTimeout(timeout), { once: true });
			recorder.onstop = () => {
				clearTimeout(timeout);
				release();
				if (controller.signal.aborted) return;
				const audio = new File(chunks, 'voice.webm', { type: recorder.mimeType });
				if (audio.size) void transcribe(audio, controller);
				else finish(controller);
			};
			finishRecording.current = () => {
				setActivity('finishing');
				recorder.stop();
			};
			recorder.start();
			setActivity('recording');
		} catch {
			if (!controller.signal.aborted) {
				cancel();
				message.warning('Разрешите доступ к микрофону или добавьте голосовое сообщение.');
			}
		}
	};

	const toggleRecording = () => {
		if (recording) {
			finishRecording.current?.();
			return;
		}
		if (operation.current) return;
		const controller = new AbortController();
		operation.current = controller;
		if (Recognition && live) startLive(new Recognition(), controller);
		else void startRecording(controller);
	};

	return { recording, pending, activity, live, toggleRecording, uploadAudio, cancel };
}
