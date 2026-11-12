import { Button, Input, Select } from 'antd';
import { Mic, Square } from 'lucide-react';
import { useEffect, useState } from 'react';
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
		selectQuickReportProject,
		busy,
	} = workspace;
	const [selectedProject, setSelectedProject] = useState<string>();
	const explicitlySelected = selectedProject === project;
	useEffect(() => {
		if (!inline && selectedProject && !explicitlySelected) setSelectedProject(undefined);
		if (!inline && explicitlySelected && day !== session.today) void changeDay(session.today);
	}, [project, selectedProject, explicitlySelected, day, session.today, inline]);
	const disabled =
		!active || !positions.length || (!inline && (!explicitlySelected || day !== session.today));
	const todayReport = workspace.todayRow;
	return (
		<section className="quick-report-composer">
			{!inline && (
				<div className="quick-report-heading">
					<h2>Что сделали сегодня?</h2>
					{explicitlySelected && workspace.data?.project?.id === project && (
						<span>
							{!positions.length
								? 'В смете объекта пока нет работ'
								: todayReport?.revision
									? 'Отчёт за сегодня есть · можно добавить работы'
									: 'Сегодня отчёт ещё не заполнен'}
						</span>
					)}
				</div>
			)}
			{!inline && (
				<label className="quick-report-project">
					<span>Объект</span>
					<Select
						aria-label="Объект для сегодняшнего отчёта"
						aria-required="true"
						placeholder="Выберите объект"
						value={explicitlySelected ? selectedProject : undefined}
						options={session.projects.map(({ id, name }) => ({ value: id, label: name }))}
						disabled={busy || audioInput.recording || audioInput.pending}
						onChange={(id) => {
							setSelectedProject(id);
							selectQuickReportProject(id);
						}}
					/>
				</label>
			)}
			<Input.TextArea
				aria-label="Сообщение о выполненных работах"
				value={freeText}
				onChange={(event) => setFreeText(event.target.value)}
				autoSize={{ minRows: 3, maxRows: 6 }}
				maxLength={8000}
				disabled={disabled}
				readOnly={audioInput.recording || audioInput.pending}
				placeholder={
					!inline && !explicitlySelected
						? 'Сначала выберите объект'
						: 'Например: 5 человек, проложили 100 м медной трубы 6 мм'
				}
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
