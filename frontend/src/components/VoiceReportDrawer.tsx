import { Upload } from 'antd';
import { SheetModal } from './SheetModal';
import { Input } from './Input';
import { Button } from './Button';
import { Mic, Sparkles, Square, Upload as UploadIcon } from 'lucide-react';
import type { WorkspaceView } from '../App';
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
	const audioBusy = audioInput.recording || audioInput.pending;
	const status = audioInput.pending
		? 'Обрабатываем аудио…'
		: audioInput.recording
			? audioInput.live
				? 'Запись идёт. Текст появляется в поле.'
				: 'Запись идёт. Текст появится после остановки.'
			: 'Запишите голосом или загрузите аудио';

	return (
		<SheetModal
			open={textOpen}
			onCancel={close}
			className="voice-report-sheet"
			title={
				<div className="voice-sheet-heading">
					<span>Голосовой ввод</span>
					{active && <small>{active.name}</small>}
				</div>
			}
			destroyOnHidden
			footer={
				<Button
					block
					type="primary"
					disabled={!freeText.trim() || audioBusy}
					loading={parsing}
					onClick={() => {
						setTextOpen(false);
						void matchReportText();
					}}
				>
					Подобрать работы
				</Button>
			}
		>
			<Input.TextArea
				className="voice-sheet-text"
				aria-label="Текст отчёта"
				value={freeText}
				onChange={(event) => setFreeText(event.target.value)}
				rows={3}
				maxLength={8000}
				readOnly={audioBusy}
				placeholder="Что сделали на объекте? Напишите или надиктуйте."
			/>
			<Button
				type="text"
				className="voice-example-link"
				icon={<Sparkles size={15} />}
				disabled={!!freeText.trim() || audioBusy}
				onClick={() => setFreeText(exampleReport)}
			>
				Пример сообщения
			</Button>
			<div className="voice-sheet-actions">
				<Button
					type="text"
					danger={audioInput.recording}
					aria-pressed={audioInput.recording}
					disabled={audioInput.pending}
					icon={audioInput.recording ? <Square size={17} /> : <Mic size={18} />}
					onClick={audioInput.toggleRecording}
				>
					{audioInput.recording ? 'Остановить' : 'Записать'}
				</Button>
				<Upload
					accept=".ogg,.opus,.mp3,.m4a,.wav,.webm"
					showUploadList={false}
					beforeUpload={audioInput.uploadAudio}
					disabled={audioBusy}
				>
					<Button type="text" icon={<UploadIcon size={17} />} disabled={audioBusy}>
						Загрузить аудио
					</Button>
				</Upload>
			</div>
			<p className="voice-sheet-status" role="status">
				{status}
			</p>
		</SheetModal>
	);
}
