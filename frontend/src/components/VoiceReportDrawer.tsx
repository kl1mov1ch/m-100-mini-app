import { Button, Drawer, Input, Upload } from 'antd';
import { LoaderCircle, Mic, Sparkles, Square, X } from 'lucide-react';
import type { WorkspaceView } from '../App';
import { ReportDraftFields } from './ReportDraftFields';
import './voice-report.css';

const exampleReport =
	'Сегодня проложили медь 6-ку\n15 м и 9-ку 15 м, изоляцию на них столько же, кабель 3х2,5 — 56 м, поставили 10\nхомутов под фреон.';

export function VoiceReportDrawer({ workspace }: { workspace: WorkspaceView }) {
	const { textOpen, setTextOpen, audioInput, active, freeText, setFreeText } = workspace;
	const close = () => {
		setTextOpen(false);
		audioInput.stop();
	};
	return (
		<Drawer
			placement="bottom"
			height="auto"
			open={textOpen}
			onClose={close}
			closable={false}
			className="voice-report-drawer"
			destroyOnHidden
		>
			<div className="voice-sheet-handle" />
			<div className="voice-sheet-heading">
				<span>{active?.name || 'Отчёт с объекта'}</span>
				<button aria-label="Закрыть голосовой ввод" onClick={close}>
					<X size={18} />
				</button>
			</div>
			<Input.TextArea
				className="voice-sheet-text"
				aria-label="Текст отчёта"
				value={freeText}
				onChange={(event) => setFreeText(event.target.value)}
				autoSize={{ minRows: 3, maxRows: 6 }}
				maxLength={8000}
				placeholder="Что сделали на объекте? Вставьте сообщение работника или надиктуйте отчёт."
			/>
			{!freeText && (
				<button className="voice-example-link" onClick={() => setFreeText(exampleReport)}>
					<Sparkles size={12} />
					Пример сообщения
				</button>
			)}
			<div
				className={'voice-microphone-area' + (freeText && !audioInput.recording ? ' compact' : '')}
			>
				<button
					className={'voice-microphone ' + (audioInput.recording ? 'recording' : '')}
					disabled={audioInput.transcribing}
					aria-label={audioInput.recording ? 'Остановить запись' : 'Начать запись'}
					onClick={audioInput.toggleRecording}
				>
					{audioInput.transcribing ? (
						<LoaderCircle size={28} className="spinning" />
					) : audioInput.recording ? (
						<Square size={23} fill="currentColor" />
					) : (
						<Mic size={30} strokeWidth={1.8} />
					)}
				</button>
				<span>
					{audioInput.transcribing
						? 'Распознаём речь…'
						: audioInput.recording
							? 'Говорите. Нажмите, чтобы закончить'
							: 'Нажмите, чтобы говорить'}
				</span>
				<Upload
					accept=".ogg,.opus,.mp3,.m4a,.wav,.webm"
					showUploadList={false}
					beforeUpload={audioInput.uploadAudio}
				>
					<Button type="text" disabled={audioInput.transcribing || audioInput.recording}>
						Добавить голосовое сообщение
					</Button>
				</Upload>
			</div>
			<ReportDraftFields workspace={workspace} />
		</Drawer>
	);
}
