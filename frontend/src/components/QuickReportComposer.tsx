import { Button, Input } from 'antd';
import { Mic, Square } from 'lucide-react';
import { useEffect } from 'react';
import type { WorkspaceView } from '../App';
import { ReportDraftFields } from './ReportDraftFields';

export function QuickReportComposer({
	workspace,
	inline = false,
}: {
	workspace: WorkspaceView;
	inline?: boolean;
}) {
	const {
		active,
		day,
		session,
		changeDay,
		project,
		positions,
		freeText,
		setFreeText,
		audioInput,
		matchReportText,
		parsing,
	} = workspace;
	useEffect(() => {
		if (!inline && day !== session.today) void changeDay(session.today);
	}, [project, day, session.today, inline]);
	const disabled = !active || !positions.length || (!inline && day !== session.today);
	const todayReport = workspace.todayRow;
	return (
		<section className="quick-report-composer">
			{!inline && (
				<div className="quick-report-heading">
					<h2>Что сделали сегодня?</h2>
					<span>
						{todayReport?.revision
							? 'Отчёт за сегодня есть · можно добавить работы'
							: 'Сегодня отчёт ещё не заполнен'}
					</span>
				</div>
			)}
			<Input.TextArea
				aria-label="Сообщение о выполненных работах"
				value={freeText}
				onChange={(event) => setFreeText(event.target.value)}
				autoSize={{ minRows: 3, maxRows: 6 }}
				maxLength={8000}
				disabled={disabled}
				readOnly={audioInput.recording || audioInput.pending}
				placeholder="Например: 5 человек, проложили 100 м медной трубы 6 мм"
			/>
			<div className="quick-report-actions">
				{!inline && (
					<Button
						aria-label={audioInput.recording ? 'Закончить диктовку' : 'Надиктовать работы'}
						disabled={disabled}
						danger={audioInput.recording}
						loading={audioInput.pending}
						icon={audioInput.recording ? <Square size={17} /> : <Mic size={19} />}
						onClick={audioInput.toggleRecording}
					/>
				)}
				<Button
					type="primary"
					disabled={disabled || !freeText.trim() || audioInput.recording || audioInput.pending}
					loading={parsing}
					onClick={matchReportText}
				>
					Подобрать работы
				</Button>
			</div>
			{audioInput.recording && (
				<p className="quick-report-voice-status" role="status">
					{audioInput.live
						? 'Говорите, текст появится в поле'
						: 'Записываем. Текст появится после остановки'}
				</p>
			)}
			{audioInput.activity === 'transcribing' && (
				<p className="quick-report-voice-status" role="status">
					Переводим запись в текст…
				</p>
			)}
			{!inline && !disabled && <ReportDraftFields workspace={workspace} />}
		</section>
	);
}
