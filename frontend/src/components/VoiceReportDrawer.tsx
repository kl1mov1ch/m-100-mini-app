import { Button, Drawer, Input, Upload } from 'antd';
import { LoaderCircle, Mic, Sparkles, Square, X } from 'lucide-react';
import type { WorkspaceView } from '../App';
import { ReportDraftFields } from './ReportDraftFields';
import './voice-report.css';

const exampleReport =
	'Сегодня проложили медь 6-ку\n15 м и 9-ку 15 м, изоляцию на них столько же, кабель 3х2,5 — 56 м, поставили 10\nхомутов под фреон.';

export function VoiceReportDrawer({ workspace }: { workspace: WorkspaceView }) {
	const {
		textOpen,
		setTextOpen,
		audioInput,
		active,
		freeText,
		setFreeText,
		matchReportText,
		parsing,
	} = workspace;
	const close = () => {
		setTextOpen(false);
		audioInput.cancel();
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
				readOnly={audioInput.recording || audioInput.pending}
				placeholder="Что сделали на объекте? Вставьте сообщение работника или надиктуйте отчёт."
			/>
			{!freeText && !audioInput.recording && !audioInput.pending && (
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
					disabled={audioInput.pending}
					aria-label={audioInput.recording ? 'Остановить запись' : 'Начать запись'}
					onClick={audioInput.toggleRecording}
				>
					{audioInput.pending ? (
						<LoaderCircle size={28} className="spinning" />
					) : audioInput.recording ? (
						<Square size={23} fill="currentColor" />
					) : (
						<Mic size={30} strokeWidth={1.8} />
					)}
				</button>
				<span>
					{audioInput.pending
						? 'Подождите…'
						: audioInput.recording
							? audioInput.live
								? 'Говорите, текст появится в поле'
								: 'Записываем. Текст появится после остановки'
							: 'Нажмите, чтобы говорить'}
				</span>
				<Upload
					accept=".ogg,.opus,.mp3,.m4a,.wav,.webm"
					showUploadList={false}
					beforeUpload={audioInput.uploadAudio}
				>
					<Button type="text" disabled={audioInput.pending || audioInput.recording}>
						Добавить голосовое сообщение
					</Button>
				</Upload>
			</div>
			<Button
				block
				type="primary"
				size="large"
				disabled={!freeText.trim() || audioInput.recording || audioInput.pending}
				loading={parsing}
				onClick={matchReportText}
			>
				Подобрать работы
			</Button>
			<ReportDraftFields workspace={workspace} />
		</Drawer>
	);
}
