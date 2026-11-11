import { Alert, Button, Collapse, Modal, Spin } from 'antd';
import { Sparkles, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import dayjs from '../lib/date';
import { Money, unit } from '../lib/format';
import type { BitrixReviewIssue } from '../types';

const quantityFormat = new Intl.NumberFormat('ru-BY', { maximumFractionDigits: 4 });

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
	const { project, reviewBitrixChanges, session } = workspace;
	const [issues, setIssues] = useState<BitrixReviewIssue[]>();
	const [advice, setAdvice] = useState<string | null>(null);
	const [error, setError] = useState('');
	const [visibleCount, setVisibleCount] = useState(20);
	const [attempt, setAttempt] = useState(0);
	useEffect(() => {
		const controller = new AbortController();
		setError('');
		setIssues(undefined);
		setAdvice(null);
		request<{ issues: BitrixReviewIssue[] }>('/bitrix/consult', {}, project, controller.signal)
			.then(({ issues }) => {
				if (controller.signal.aborted) return;
				setIssues(issues);
				if (!issues.length || !session.ai_connected) return;
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
	return (
		<Modal
			open
			title="Различия с Битрикс24"
			onCancel={close}
			footer={
				issues?.length ? (
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
				) : issues.length ? (
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
						<Collapse
							defaultActiveKey={['0']}
							items={issues.slice(0, visibleCount).map((issue, index) => ({
								key: String(index),
								label: (
									<span className="bitrix-review-label">
										<b>{issue.title}</b>
										{issue.position && <small>{issue.position}</small>}
										{issue.date && <small>{dayjs(issue.date).format('D MMMM YYYY')}</small>}
									</span>
								),
								children: <IssueDetails issue={issue} />,
							}))}
						/>
						{visibleCount < issues.length && (
							<Button onClick={() => setVisibleCount(visibleCount + 20)}>Показать ещё</Button>
						)}
					</>
				) : (
					<Alert type="success" showIcon message="Различий нет" />
				)}
			</div>
		</Modal>
	);
}
