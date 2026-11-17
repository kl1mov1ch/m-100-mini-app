import { Alert, App as AntApp, Badge, Button, Modal } from 'antd';
import { Bell, ChevronRight, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import './table-notifications.css';

type TableIssue = {
	kind: string;
	title: string;
	position?: string;
	sheet?: string;
	cell?: string;
	row?: number;
	date?: string;
	local?: number;
	remote?: number;
	suggested?: number;
	unit?: string;
	advice?: string;
};

type TableNotice = {
	project_id: string;
	project_name: string;
	issues: TableIssue[];
	version: string | null;
};

const path = '/profile/table-notifications';
const numbers = new Intl.NumberFormat('ru-BY', { maximumFractionDigits: 4 });

export function useTableNotifications(userId?: string, role?: string) {
	const [notices, setNotices] = useState<TableNotice[]>([]);
	const [error, setError] = useState('');
	const pending = useRef<AbortController | null>(null);
	const reload = useCallback(async () => {
		if (!userId || !role) return;
		pending.current?.abort();
		const controller = new AbortController();
		pending.current = controller;
		try {
			const next = await request<TableNotice[]>(path, undefined, undefined, controller.signal);
			if (controller.signal.aborted) return;
			setNotices(next);
			setError('');
		} catch (problem) {
			if (!controller.signal.aborted) setError((problem as Error).message);
		}
	}, [userId, role]);
	useEffect(() => {
		setNotices([]);
		setError('');
		const refresh = () => {
			if (!document.hidden) void reload();
		};
		refresh();
		const timer = window.setInterval(refresh, 60000);
		document.addEventListener('visibilitychange', refresh);
		return () => {
			window.clearInterval(timer);
			document.removeEventListener('visibilitychange', refresh);
			pending.current?.abort();
		};
	}, [reload]);
	return {
		notices,
		error,
		count: notices.reduce((sum, item) => sum + item.issues.length, 0),
		reload,
	};
}

export function TableNotifications({
	workspace,
	inbox,
}: {
	workspace: WorkspaceView;
	inbox: ReturnType<typeof useTableNotifications>;
}) {
	const { message } = AntApp.useApp();
	const [open, setOpen] = useState(false);
	const [loading, setLoading] = useState<string | null>(null);
	const [feedback, setFeedback] = useState<Record<string, { error: boolean; text: string }>>({});

	async function refresh(notice: TableNotice) {
		const id = notice.project_id;
		setLoading(id);
		try {
			const remaining = await request<TableNotice | null>(
				path + '/' + encodeURIComponent(id) + '/refresh',
				{
					version: notice.version,
				},
			);
			if (workspace.project === id) await workspace.loadData(id, false, true);
			if (!remaining) message.success('Данные сверены');
			setFeedback((notes) => ({
				...notes,
				[id]: {
					error: false,
					text: remaining ? 'Таблица проверена. Ниже остались замечания.' : 'Данные сверены.',
				},
			}));
		} catch (problem) {
			setFeedback((notes) => ({
				...notes,
				[id]: { error: true, text: (problem as Error).message },
			}));
		} finally {
			await inbox.reload();
			setLoading(null);
		}
	}

	return (
		<>
			<button
				className="settings-menu"
				onClick={() => {
					setOpen(true);
					void inbox.reload();
				}}
			>
				<span className="settings-icon">
					<Bell size={21} />
				</span>
				<span>
					<b>Уведомления по таблицам</b>
					<small>Расхождения и ошибки Битрикс24</small>
				</span>
				<Badge count={inbox.count} />
				<ChevronRight size={18} aria-hidden />
			</button>
			<Modal
				title="Уведомления по таблицам"
				open={open}
				footer={null}
				onCancel={() => setOpen(false)}
			>
				<div className="table-notifications">
					{inbox.error && <Alert type="error" message={inbox.error} />}
					{!inbox.notices.length && !inbox.error && <p>Нет открытых замечаний по таблицам.</p>}
					{inbox.notices.map((notice) => (
						<section key={notice.project_id} className="table-notice-card">
							<h3>{notice.project_name}</h3>
							{feedback[notice.project_id] && (
								<Alert
									type={feedback[notice.project_id].error ? 'error' : 'info'}
									message={feedback[notice.project_id].text}
								/>
							)}
							<ul>
								{notice.issues.map((issue, index) => (
									<li key={index}>
										<strong>{issue.title}</strong>
										{issue.position && <span>{issue.position}</span>}
										<small>
											{[
												issue.sheet,
												issue.cell || (issue.row ? 'Строка ' + issue.row : ''),
												issue.date,
											]
												.filter(Boolean)
												.join(' · ')}
										</small>
										{typeof issue.local === 'number' && (
											<span>
												В приложении {numbers.format(issue.local)} {issue.unit}
											</span>
										)}
										{typeof issue.remote === 'number' && (
											<span>
												В таблице {numbers.format(issue.remote)} {issue.unit}
											</span>
										)}
										{issue.advice && <small>{issue.advice}</small>}
									</li>
								))}
							</ul>
							<Button
								type="primary"
								icon={<RefreshCw size={16} />}
								loading={loading === notice.project_id}
								disabled={
									loading !== null ||
									(!!notice.version && workspace.project === notice.project_id && workspace.dirty)
								}
								onClick={() => void refresh(notice)}
							>
								{notice.version ? 'Загрузить из таблицы' : 'Проверить таблицу'}
							</Button>
							{notice.version && workspace.project === notice.project_id && workspace.dirty && (
								<small>Сначала сохраните текущий отчёт.</small>
							)}
						</section>
					))}
				</div>
			</Modal>
		</>
	);
}
