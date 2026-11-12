import { Alert, App, Button, Collapse, Modal, Spin } from 'antd';
import { Sparkles, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import { Money, unit } from '../lib/format';
import type { BitrixReviewIssue } from '../types';

const quantityFormat = new Intl.NumberFormat('ru-BY', { maximumFractionDigits: 4 });
type Conflict = {
	version: string;
	days: number;
	positions: number;
	deleted: number;
	fields: number;
	can_write: boolean;
};

function IssueDetails({ issue }: { issue: BitrixReviewIssue }) {
	const location = [issue.sheet, issue.cell || (issue.row ? `строка ${issue.row}` : null)]
		.filter(Boolean)
		.join(' · ');
	const values = [
		[issue.kind === 'report' ? 'В отчёте' : 'В приложении', issue.local],
		['В Битрикс24', issue.remote],
		['Предлагаемое значение', issue.suggested],
	] as const;
	const display = (value: number) =>
		issue.unit === 'BYN' ? (
			<Money value={value} />
		) : (
			`${quantityFormat.format(value)} ${unit(issue.unit || '')}`
		);
	return (
		<div className="bitrix-review-details">
			{location && <small>{location}</small>}
			{issue.value && <span>{issue.value}</span>}
			{values.map(([label, value]) =>
				value === undefined ? null : (
					<div className="bitrix-review-value" key={label}>
						<span>{label}</span>
						<b>{display(value)}</b>
					</div>
				),
			)}
			{issue.planned !== undefined && issue.completed !== undefined && (
				<small>
					План {display(issue.planned)} · выполнено {display(issue.completed)}
				</small>
			)}
			{issue.formula && (
				<div className="bitrix-review-value">
					<span>Формула остатка</span>
					<code>{issue.formula}</code>
				</div>
			)}
			<p>{issue.advice}</p>
		</div>
	);
}

export function BitrixReviewModal({
	workspace,
	close,
}: {
	workspace: WorkspaceView;
	close: () => void;
}) {
	const { project, reviewBitrixChanges, session, refresh } = workspace;
	const { modal, message } = App.useApp();
	const [issues, setIssues] = useState<BitrixReviewIssue[]>();
	const [conflicts, setConflicts] = useState<Conflict | null>(null);
	const [saving, setSaving] = useState(false);
	const [advice, setAdvice] = useState<string | null>(null);
	const [error, setError] = useState('');
	const [attempt, setAttempt] = useState(0);
	useEffect(() => {
		const controller = new AbortController();
		setError('');
		setIssues(undefined);
		setConflicts(null);
		setAdvice(null);
		request<{ issues: BitrixReviewIssue[]; conflicts: Conflict | null }>(
			'/bitrix/consult',
			{},
			project,
			controller.signal,
		)
			.then(({ issues, conflicts }) => {
				if (controller.signal.aborted) return;
				setIssues(issues);
				setConflicts(conflicts);
				if ((!issues.length && !conflicts) || !session.ai_connected) return;
				void request<{ advice: string | null }>(
					'/bitrix/consult?explain=true',
					{},
					project,
					controller.signal,
				)
					.then(({ advice }) => {
						if (!controller.signal.aborted) setAdvice(advice);
					})
					.catch(() => {});
			})
			.catch((failure) => {
				if (!controller.signal.aborted) setError((failure as Error).message);
			});
		return () => controller.abort();
	}, [project, attempt, session.ai_connected]);
	const replace = (direction: 'app' | 'table') => {
		if (!conflicts || saving) return;
		modal.confirm({
			title: direction === 'app' ? 'Заменить в приложении?' : 'Заменить в таблице?',
			content:
				direction === 'app'
					? `Приложение примет значения из Битрикс24.${conflicts.deleted ? ' Пустые объёмы станут нулевыми.' : ''}${workspace.dirty ? ' Текущий черновик будет закрыт.' : ''}`
						: `Значения из приложения заменят данные на рабочем листе Битрикс24.${workspace.dirty ? ' Текущий черновик будет закрыт.' : ''}`,
			okText: 'Заменить',
			cancelText: 'Отмена',
			async onOk() {
				setSaving(true);
				try {
					await request('/bitrix/reconcile', { direction, version: conflicts.version }, project);
					await refresh();
					message.success(direction === 'app' ? 'Отчёты обновлены' : 'Таблица обновлена');
					close();
				} catch (error) {
					setError((error as Error).message);
				} finally {
					setSaving(false);
				}
			},
		});
	};
	return (
		<Modal
			open
			title="Различия с Битрикс24"
			onCancel={close}
			footer={
				issues?.length && !conflicts ? (
					<Button
						type="primary"
						onClick={() => {
							close();
							void reviewBitrixChanges();
						}}
					>
						Открыть проверку таблицы
					</Button>
				) : null
			}
		>
			<div className="bitrix-review">
				{error ? (
					<>
						<Alert type="warning" showIcon icon={<TriangleAlert size={17} />} message={error} />
						<Button onClick={() => setAttempt(attempt + 1)}>Повторить</Button>
					</>
				) : !issues ? (
					<div className="bitrix-review-loading">
						<Spin size="small" /> Сравниваем данные
					</div>
				) : issues.length || conflicts ? (
					<>
						{advice && (
							<Alert
								type="info"
								showIcon
								icon={<Sparkles size={17} />}
								message="Подсказка ИИ"
								description={advice}
							/>
						)}
						{conflicts && (
							<>
								<b>
									{[
										conflicts.days ? `Отчёты за ${conflicts.days} дн.` : '',
										conflicts.fields ? `Смета · ${conflicts.fields} полей` : '',
									]
										.filter(Boolean)
										.join(' · ')}
								</b>
								<Button type="primary" loading={saving} onClick={() => replace('app')}>
									Заменить в приложении
								</Button>
								<Button disabled={!conflicts.can_write || saving} onClick={() => replace('table')}>
									Заменить в таблице
								</Button>
							</>
						)}
						{issues.length > 0 && (
							<Collapse
								items={issues.slice(0, 5).map((issue, index) => ({
									key: String(index),
									label: (
										<span className="bitrix-review-label">
											<b>{issue.title}</b>
											{issue.position && <small>{issue.position}</small>}
										</span>
									),
									children: <IssueDetails issue={issue} />,
								}))}
							/>
						)}
						{conflicts && issues.length > 0 && (
							<Button
								type="link"
								onClick={() => {
									close();
									void reviewBitrixChanges();
								}}
							>
								Проверить смету
							</Button>
						)}
					</>
				) : (
					<Alert type="success" showIcon message="Различий нет" />
				)}
			</div>
		</Modal>
	);
}
