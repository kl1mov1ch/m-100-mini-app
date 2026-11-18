import { Alert, App as AntApp, Badge } from 'antd';
import { Button } from '../components/Button';
import { SheetModal as Modal } from '../components/SheetModal';
import { RefreshCw, X } from 'lucide-react';
import { Bell, ChevronRight } from '../components/kit-icons';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import { Select } from '../components/Select';
import './table-notifications.css';

type TableIssue = {
	id: string;
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
	author?: string;
	reason?: string;
	retrying?: boolean;
};

type TableNotice = {
	project_id: string;
	project_name: string;
	can_check_table: boolean;
	issues: TableIssue[];
	version: string | null;
};

const path = '/profile/table-notifications';
const numbers = new Intl.NumberFormat('ru-BY', { maximumFractionDigits: 4 });
const issueGroups = [
	{ title: 'Смета и расценки', kinds: ['planned', 'rate', 'remaining'] },
	{ title: 'Объёмы в отчётах', kinds: ['report'] },
	{ title: 'Листы и ячейки', kinds: ['layout', 'cell'] },
	{ title: 'Подключение', kinds: ['connection'] },
	{ title: 'Ошибки отправки', kinds: ['sync'] },
];

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
	const [selectedProject, setSelectedProject] = useState('');
	const [loading, setLoading] = useState<string | null>(null);
	const [feedback, setFeedback] = useState<Record<string, { error: boolean; text: string }>>({});
	const selectedNotice =
		inbox.notices.find((item) => item.project_id === selectedProject) ?? inbox.notices[0];

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

	async function dismiss(notice: TableNotice, issueId?: string) {
		setLoading(notice.project_id);
		try {
			await request(path + '/' + encodeURIComponent(notice.project_id) + '/dismiss', {
				issue_id: issueId ?? null,
			});
			await inbox.reload();
		} catch (problem) {
			message.error((problem as Error).message);
		} finally {
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
					{inbox.notices.length > 1 && (
						<Select
							aria-label="Объект"
							value={selectedNotice?.project_id}
							onChange={setSelectedProject}
							options={inbox.notices.map((item) => ({
								value: item.project_id,
								label: `${item.project_name} · ${item.issues.length}`,
							}))}
						/>
					)}
					{(selectedNotice ? [selectedNotice] : []).map((notice) => (
						<details key={notice.project_id} className="table-notice-card" open>
							<summary>
								<strong>{notice.project_name}</strong>
								<Badge count={notice.issues.length} />
							</summary>
							{feedback[notice.project_id] && (
								<Alert
									type={feedback[notice.project_id].error ? 'error' : 'info'}
									message={feedback[notice.project_id].text}
								/>
							)}
							{issueGroups.map(({ title, kinds }) => {
								const issues = notice.issues.filter((issue) => kinds.includes(issue.kind));
								if (!issues.length) return null;
								return (
									<details className="table-notice-group" key={title} open={kinds.includes('sync')}>
										<summary>
											{title}
											<span>{issues.length}</span>
										</summary>
										<ul>
											{issues.map((issue) => (
												<li key={issue.id}>
													<div className="table-notice-line">
														<strong>{issue.title}</strong>
														<Button
															type="text"
															size="small"
															icon={<X size={16} />}
															aria-label={'Убрать уведомление: ' + issue.title}
															disabled={loading !== null}
															onClick={() => void dismiss(notice, issue.id)}
														/>
													</div>
													{issue.position && <span>{issue.position}</span>}
													{issue.author && <span>Автор отчёта · {issue.author}</span>}
													{issue.reason && <span>{issue.reason}</span>}
													{issue.retrying && <small>Запланирована повторная отправка</small>}
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
													{typeof issue.suggested === 'number' && issue.kind === 'remaining' && (
														<span>
															Расчётный остаток {numbers.format(issue.suggested)} {issue.unit}
														</span>
													)}
													{issue.advice && !['planned', 'rate', 'report'].includes(issue.kind) && (
														<small>{issue.advice}</small>
													)}
													{issue.kind === 'sync' && issue.date && (
														<Button
															type="link"
															onClick={() => {
																setOpen(false);
																workspace.openHistoryReport(notice.project_id, issue.date!);
															}}
														>
															Открыть отчёт
														</Button>
													)}
												</li>
											))}
										</ul>
									</details>
								);
							})}
							<div className="table-notice-actions">
								{notice.can_check_table && (
									<Button
										type="primary"
										icon={<RefreshCw size={16} />}
										loading={loading === notice.project_id}
										disabled={
											loading !== null ||
											(!!notice.version &&
												workspace.project === notice.project_id &&
												workspace.dirty)
										}
										onClick={() => void refresh(notice)}
									>
										{notice.version ? 'Применить данные Битрикс24' : 'Проверить таблицу'}
									</Button>
								)}
								{!workspace.isAdmin &&
									notice.issues.some(({ kind }) =>
										['layout', 'cell', 'remaining'].includes(kind),
									) && (
										<Button
											onClick={() => {
												setOpen(false);
												workspace.selectObject(notice.project_id);
												workspace.openObjectSection('table');
											}}
										>
											Открыть таблицу проекта
										</Button>
									)}
								<Button
									type="text"
									disabled={loading !== null}
									onClick={() => void dismiss(notice)}
								>
									Убрать все по объекту
								</Button>
							</div>
							{notice.version && workspace.project === notice.project_id && workspace.dirty && (
								<small>Сначала сохраните текущий отчёт.</small>
							)}
						</details>
					))}
				</div>
			</Modal>
		</>
	);
}
