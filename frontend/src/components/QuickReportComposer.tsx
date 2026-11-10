import { Button, Input } from 'antd';
import { Mic } from 'lucide-react';
import { useEffect } from 'react';
import type { WorkspaceView } from '../App';
import { ReportDraftFields } from './ReportDraftFields';

export function QuickReportComposer({ workspace }: { workspace: WorkspaceView }) {
	const {
		active,
		day,
		session,
		changeDay,
		project,
		positions,
		freeText,
		setFreeText,
		setTextOpen,
	} = workspace;
	useEffect(() => {
		if (day !== session.today) void changeDay(session.today);
	}, [project, day, session.today]);
	const disabled = !active || !positions.length || day !== session.today;
	return (
		<section className="quick-report-composer">
			<div className="quick-report-heading">
				<h2>Что сделали сегодня?</h2>
				<span>{active?.name || 'Выберите объект'}</span>
			</div>
			<Input.TextArea
				aria-label="Сообщение о выполненных работах"
				value={freeText}
				onChange={(event) => setFreeText(event.target.value)}
				autoSize={{ minRows: 3, maxRows: 6 }}
				maxLength={8000}
				disabled={disabled}
				placeholder="Например: работали 5 человек, проложили медь 6-ку 100 м и фреонопровод 120 м"
			/>
			<div className="quick-report-actions">
				<span>Своими словами · текстом или голосом</span>
				<Button
					aria-label="Надиктовать работы за сегодня"
					disabled={disabled}
					icon={<Mic size={19} />}
					onClick={() => setTextOpen(true)}
				/>
			</div>
			{!disabled && <ReportDraftFields workspace={workspace} />}
		</section>
	);
}
