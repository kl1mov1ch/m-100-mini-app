import { App } from 'antd';
import { Input } from './Input';
import { Button } from './Button';
import { Mic, RotateCcw, Sparkles, Square } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useAudioInput } from '../hooks/useAudioInput';
import { request } from '../lib/api';

export function NoteInput({
	project,
	scope,
	value,
	onChange,
	label,
	maxLength = 1000,
}: {
	project: string;
	scope: string;
	value: string;
	onChange: (value: string) => void;
	label: string;
	maxLength?: number;
}) {
	const { message } = App.useApp();
	const [before, setBefore] = useState('');
	const [working, setWorking] = useState(false);
	const active = useRef<AbortController | null>(null);
	useEffect(() => () => active.current?.abort(), [project, scope]);
	const edit = (text: string) => {
		setBefore('');
		onChange(text.slice(0, maxLength));
	};
	const audio = useAudioInput(project, scope, value, edit);
	const polish = async () => {
		const controller = new AbortController();
		active.current = controller;
		setWorking(true);
		try {
			const result = await request<{ text: string; engine: string }>(
				'/object/polish-note',
				{ text: value, max_length: maxLength },
				project,
				controller.signal,
			);
			if (controller.signal.aborted) return;
			if (result.text && result.text !== value && result.text.length <= maxLength) {
				setBefore((original) => original || value);
				onChange(result.text);
				message.success(
					result.engine === 'ai' ? 'Текст отредактирован' : 'Базовые правки применены',
				);
			} else {
				message.info('Подходящих правок нет');
			}
		} catch (failure) {
			if (!controller.signal.aborted) message.error((failure as Error).message);
		} finally {
			if (!controller.signal.aborted) setWorking(false);
		}
	};
	return (
		<div className="work-note">
			<Input.TextArea
				aria-label={label}
				value={value}
				placeholder="Например, этаж или причина переноса"
				maxLength={maxLength}
				autoSize={{ minRows: 1, maxRows: 5 }}
				readOnly={working || audio.recording || audio.pending}
				onChange={(event) => edit(event.target.value)}
			/>
			<div className="note-actions">
				<Button
					aria-label={audio.recording ? 'Закончить диктовку' : 'Надиктовать примечание'}
					icon={audio.recording ? <Square size={16} /> : <Mic size={17} />}
					danger={audio.recording}
					loading={audio.pending}
					disabled={working}
					onClick={audio.toggleRecording}
				/>
				<Button
					type="text"
					icon={<Sparkles size={16} />}
					loading={working}
					disabled={!value.trim() || audio.recording || audio.pending}
					onClick={() => void polish()}
				>
					Улучшить текст
				</Button>
				{before && (
					<Button
						type="text"
						size="small"
						className="note-restore"
						title="Вернуть исходный текст"
						aria-label="Вернуть исходный текст"
						disabled={working || audio.recording || audio.pending}
						icon={<RotateCcw size={16} />}
						onClick={() => edit(before)}
					>
						Исходный
					</Button>
				)}
			</div>
			{audio.recording && <span role="status">Идёт диктовка…</span>}
		</div>
	);
}
