import { App, Button, Empty, Select, Spin, Modal } from 'antd';
import { useEffect, useState } from 'react';
import { ArrowDownToLine, ChevronRight, History, RefreshCw, SlidersHorizontal } from 'lucide-react';
import { DatePicker } from '../components/ResponsiveDatePicker';
import { Status } from '../components/SyncStatus';
import { request, headers } from '../lib/api';
import dayjs from '../lib/date';
import { Money } from '../lib/format';
import type { HistoryRow } from '../types';
import type { WorkspaceView } from '../App';

type Analytics = {
	rows: (HistoryRow & { project_id: string; project_name: string; owner_name: string })[];
	summary: {
		amount: number;
		reports: number;
		positions: number;
		projects: number;
		days: number;
		worker_days: number;
		per_person: number | null;
		pending: number;
	};
};

export function ReportsPage({ workspace }: { workspace: WorkspaceView }) {
	const { session, isAdmin, showChanges, openHistoryReport } = workspace;
	const { message } = App.useApp();
	const [project, setProject] = useState(workspace.active?.id || 'all');
	const [owner, setOwner] = useState('all');
	const [start, setStart] = useState('');
	const [end, setEnd] = useState('');
	const [sort, setSort] = useState('date_desc');
	const [data, setData] = useState<Analytics>();
	const [loading, setLoading] = useState(false);
	const [version, setVersion] = useState(0);
	const [filtersOpen, setFiltersOpen] = useState(false);
	const params = new URLSearchParams({ sort });
	if (project !== 'all') params.set('project_id', project);
	if (owner !== 'all') params.set('owner_id', owner);
	if (start) params.set('start', start);
	if (end) params.set('end', end);
	const query = params.toString();
	useEffect(() => {
		const controller = new AbortController();
		setLoading(true);
		request<Analytics>('/analytics?' + query, undefined, undefined, controller.signal)
			.then(setData)
			.catch((error) => {
				if (!controller.signal.aborted) message.error(error.message);
			})
			.finally(() => {
				if (!controller.signal.aborted) setLoading(false);
			});
		return () => controller.abort();
	}, [query, version]);
	const exportReport = async () => {
		try {
			const response = await fetch('/api/analytics/export.xlsx?' + query, { headers: headers() });
			if (!response.ok) throw new Error('Не удалось сформировать Excel');
			const url = URL.createObjectURL(await response.blob());
			const link = document.createElement('a');
			link.href = url;
			link.download = 'Журнал работ.xlsx';
			link.click();
			setTimeout(() => URL.revokeObjectURL(url), 1000);
		} catch (error) {
			message.error((error as Error).message);
		}
	};
	const summary = data?.summary;
	return (
		<>
			<div className="page-title">
				<div>
					<span className="overline">ПОКАЗАТЕЛИ И ВЫРАБОТКА</span>
					<h1>История работ</h1>
				</div>
				<Button icon={<ArrowDownToLine size={17} />} onClick={exportReport}>
					Excel
				</Button>
			</div>
			<section className="report-filter-compact">
				<Select
					aria-label="Выбранный объект истории"
					value={project}
					onChange={setProject}
					options={[
						{ value: 'all', label: 'Все объекты' },
						...session.projects.map((item) => ({ value: item.id, label: item.name })),
					]}
				/>
				<Button icon={<SlidersHorizontal size={16} />} onClick={() => setFiltersOpen(true)}>
					Фильтры
				</Button>
				<Button
					aria-label="Обновить историю"
					icon={<RefreshCw size={16} />}
					loading={loading}
					onClick={() => setVersion((value) => value + 1)}
				/>
				<small>
					{start || end
						? `${start ? dayjs(start).format('DD.MM.YYYY') : 'Начало'} — ${end ? dayjs(end).format('DD.MM.YYYY') : 'Сегодня'}`
						: 'За всё время'}
				</small>
			</section>
			<Modal
				title="Фильтры истории"
				open={filtersOpen}
				onCancel={() => setFiltersOpen(false)}
				footer={
					<>
						<Button
							onClick={() => {
								setStart('');
								setEnd('');
								setOwner('all');
								setSort('date_desc');
							}}
						>
							Сбросить
						</Button>
						<Button type="primary" onClick={() => setFiltersOpen(false)}>
							Готово
						</Button>
					</>
				}
			>
				<div className="report-filter-card">
					<div className="date-filter-row">
						<DatePicker
							aria-label="Начало периода"
							placeholder="С даты"
							value={start ? dayjs(start) : null}
							format="DD.MM.YYYY"
							onChange={(date) => setStart(date?.format('YYYY-MM-DD') || '')}
						/>
						<DatePicker
							aria-label="Конец периода"
							placeholder="По дату"
							value={end ? dayjs(end) : null}
							format="DD.MM.YYYY"
							onChange={(date) => setEnd(date?.format('YYYY-MM-DD') || '')}
						/>
					</div>
					<Select
						aria-label="Объект в истории"
						value={project}
						onChange={setProject}
						options={[
							{ value: 'all', label: 'Все объекты' },
							...session.projects.map((item) => ({ value: item.id, label: item.name })),
						]}
					/>
					{isAdmin && (
						<Select
							aria-label="Мастер в истории"
							value={owner}
							onChange={setOwner}
							options={[
								{ value: 'all', label: 'Все мастера' },
								...[
									...new Map(
										session.projects.map((item) => [item.owner_id, item.owner_name]),
									).entries(),
								].map(([value, label]) => ({ value, label })),
							]}
						/>
					)}
					<Select
						aria-label="Порядок отчётов"
						value={sort}
						onChange={setSort}
						options={[
							{ value: 'date_desc', label: 'Сначала новые' },
							{ value: 'date_asc', label: 'Сначала старые' },
							{ value: 'amount_desc', label: 'Сначала большая выработка' },
							{ value: 'amount_asc', label: 'Сначала меньшая выработка' },
						]}
					/>
					<div className="report-filter-actions">
						<Button
							icon={<RefreshCw size={15} />}
							onClick={() => setVersion((value) => value + 1)}
							loading={loading}
						>
							Обновить
						</Button>
						<Button icon={<History size={15} />} onClick={showChanges}>
							Изменения объекта
						</Button>
					</div>
				</div>
			</Modal>
			{summary && (
				<section className="report-metrics">
					<div className="metric-primary">
						<span>Выработка за период</span>
						<strong>
							<Money value={summary.amount} />
						</strong>
						<small>
							{summary.days} дней · {summary.projects} объектов
						</small>
					</div>
					<div>
						<span>Выполнено работ</span>
						<strong>{summary.positions}</strong>
						<small>{summary.reports} отчётов</small>
					</div>
					<div>
						<span>Средняя доля</span>
						<strong>
							{summary.per_person !== null ? <Money value={summary.per_person} /> : '—'}
						</strong>
						<small>На человеко-день</small>
					</div>
					<div>
						<span>Бригада за период</span>
						<strong>{summary.worker_days}</strong>
						<small>Человеко-дней · {summary.pending} ждут Битрикс</small>
					</div>
				</section>
			)}
			<Spin spinning={loading}>
				<div className="history-list">
					{data?.rows.map((row) => (
						<section className="history-card" key={row.project_id + row.date}>
							<button
								className="history-open"
								onClick={() => openHistoryReport(row.project_id, row.date)}
							>
								<div className="history-day">
									<span>{dayjs(row.date).format('DD')}</span>
									<small>{dayjs(row.date).format('MMM')}</small>
								</div>
								<div className="history-main">
									<b>{row.project_name}</b>
									<small>
										{dayjs(row.date).format('D MMMM YYYY')} · {row.owner_name}
									</small>
								</div>
								<ChevronRight size={17} />
							</button>
							<div className="history-finance">
								<span>
									За день
									<strong>
										<Money value={row.amount} />
									</strong>
								</span>
								<span>
									На человека
									<strong>{row.crew_count ? <Money value={row.per_person} /> : '—'}</strong>
								</span>
							</div>
							<div className="history-bottom">
								<span>
									{row.positions} работ{row.crew_count ? ` · ${row.crew_count} чел.` : ''}
								</span>
								<Status status={row.sync_status} />
							</div>
						</section>
					))}
				</div>
				{!loading && !data?.rows.length && <Empty description="За выбранный период отчётов нет" />}
			</Spin>
		</>
	);
}
