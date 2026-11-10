import { Button, Drawer, Input, Upload } from 'antd';
import { LoaderCircle, Mic, Sparkles, Square, X } from 'lucide-react';
import type { WorkspaceView } from '../App';
import { nf, shortName, unit } from '../lib/format';
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
		parsed,
		parsing,
		byId,
		setLines,
		setReportText,
	} = workspace;
	const close = () => {
		setTextOpen(false);
		audioInput.stop();
	};
	const addRecognizedWorks = () => {
		setLines((currentLines) => {
			const mergedLines = currentLines.map((line) => ({ ...line }));
			for (const recognizedLine of parsed) {
				const existingLine = recognizedLine.item_id
					? mergedLines.find((line) => line.item_id === recognizedLine.item_id)
					: undefined;
				if (existingLine && recognizedLine.quantity !== null && existingLine.quantity !== null) {
					existingLine.quantity += recognizedLine.quantity;
					continue;
				}
				mergedLines.push({ ...recognizedLine });
			}
			return mergedLines;
		});
		setReportText(freeText);
		setTextOpen(false);
		setFreeText('');
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
			<div className="voice-microphone-area">
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
			{(parsing || parsed.length > 0) && (
				<div className="voice-recognition-results">
					<div className="voice-recognition-heading">
						<b>{parsing ? 'Подбираем работы…' : `${parsed.length} работ из сметы объекта`}</b>
						{parsing && <LoaderCircle size={14} className="spinning" />}
					</div>
					<div className="voice-recognized-list">
						{parsed.map((line, index) => {
							const position = line.item_id ? byId[line.item_id] : null;
							return (
								<div
									className={
										'voice-recognized-card ' + (!position || !line.quantity ? 'needs-review' : '')
									}
									key={index}
								>
									<span>
										<b>{position ? shortName(position) : line.raw || 'Уточните работу'}</b>
										{(!position || !line.quantity) && (
											<small>Нужно уточнить {position ? 'объём' : 'позицию'}</small>
										)}
									</span>
									<strong>
										{line.quantity ? nf.format(line.quantity) : '—'}{' '}
										{position ? unit(position.unit) : ''}
									</strong>
								</div>
							);
						})}
					</div>
					{parsed.length > 0 && (
						<Button
							block
							type="primary"
							size="large"
							disabled={parsing}
							onClick={addRecognizedWorks}
						>
							Проверить карточки работ
						</Button>
					)}
				</div>
			)}
		</Drawer>
	);
}
