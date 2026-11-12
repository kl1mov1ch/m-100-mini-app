import { Button, Input, Select } from 'antd';
import { Mic, Square } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { WorkspaceView } from '../App';
import { ReportDraftFields } from './ReportDraftFields';
import { shortName, unit } from '../lib/format';

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
	const [exampleIndex, setExampleIndex] = useState(0);
	const explicitlySelected = selectedProject === project;
	const examples = [...positions]
		.sort((left, right) => shortName(left).length - shortName(right).length)
		.slice(0, 3);
	const example = examples[exampleIndex % Math.max(examples.length, 1)];
	useEffect(() => {
		setExampleIndex(0);
	}, [project]);
	useEffect(() => {
		if ((!inline && !explicitlySelected) || freeText || examples.length < 2) return;
		const timer = window.setInterval(() => setExampleIndex((current) => current + 1), 7000);
		return () => window.clearInterval(timer);
	}, [project, inline, explicitlySelected, freeText, examples.length]);
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
				<div className="quick-report-project">
					<Select
						variant="borderless"
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
				</div>
			)}
			<Input.TextArea
				aria-label="Сообщение о выполненных работах"
				value={freeText}
				onChange={(event) => setFreeText(event.target.value)}
				autoSize={{ minRows: 2, maxRows: 5 }}
				maxLength={8000}
				disabled={disabled}
				readOnly={audioInput.recording || audioInput.pending}
				placeholder={
					!inline && !explicitlySelected
						? 'Сначала выберите объект'
						: example
							? 'Например: 3 человека. ' + shortName(example) + ' — 1 ' + unit(example.unit)
							: 'Сколько человек работало и что сделали?'
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
