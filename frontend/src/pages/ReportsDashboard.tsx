import { App, Button, Empty, Select, Spin, Modal } from 'antd';
import { useEffect, useState } from 'react';
import { ArrowDownToLine, History, RefreshCw, SlidersHorizontal } from 'lucide-react';
import { DatePicker } from '../components/ResponsiveDatePicker';
import { HistoryReportDetails } from '../components/HistoryReportDetails';
import { Status } from '../components/SyncStatus';
import { CompactWorkEditor } from '../components/CompactRow';
import { request } from '../lib/api';
import dayjs from '../lib/date';
import { Money, countLabel } from '../lib/format';
import { downloadReport } from '../lib/report-download';
import type { HistoryRow } from '../types';
import type { WorkspaceView } from '../App';

type Analytics = {
	work_dates?: string[];
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
	const [downloading, setDownloading] = useState(false);
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
		setDownloading(true);
		try {
			await downloadReport('/analytics/export.xlsx?' + query);
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setDownloading(false);
		}
	};
	const summary = data?.summary;
	return (
		<>
			<div className="page-title">
				<div>
					<h1>История работ</h1>
				</div>
				<Button icon={<ArrowDownToLine size={17} />} loading={downloading} onClick={exportReport}>
					Скачать Excel
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
							workDates={data?.work_dates || []}
							range={{ start, end }}
							onChange={(date) => {
								const next = date?.format('YYYY-MM-DD') || '';
								setStart(next);
								if (end && next > end) setEnd('');
							}}
						/>
						<DatePicker
							aria-label="Конец периода"
							placeholder="По дату"
							value={end ? dayjs(end) : null}
							format="DD.MM.YYYY"
							workDates={data?.work_dates || []}
							range={{ start, end }}
							disabledDate={(date) => !!start && date.format('YYYY-MM-DD') < start}
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
							{countLabel(summary.days, 'день', 'дня', 'дней')} ·{' '}
							{countLabel(summary.projects, 'объект', 'объекта', 'объектов')}
						</small>
					</div>
					<div>
						<span>Выполнено работ</span>
						<strong>{summary.positions}</strong>
						<small>{countLabel(summary.reports, 'отчёт', 'отчёта', 'отчётов')}</small>
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
						<strong>{summary.worker_days || '—'}</strong>
						<small>
							{summary.worker_days ? 'Человеко-дней' : 'Бригада не указана'}
							{summary.pending > 0 ? ` · ${summary.pending} ждут Битрикс` : ''}
						</small>
					</div>
				</section>
			)}
			<Spin spinning={loading}>
				<div className="status-legend">
					<span>
						<i />
						Не отправлен
					</span>
					<span className="sent">
						<i />В Битрикс24
					</span>
				</div>
				<div className="history-list compact-list">
					{data?.rows.map((row) => (
						<CompactWorkEditor
							key={row.project_id + row.date}
							footer={
								<Button
									type="primary"
									block
									onClick={() => openHistoryReport(row.project_id, row.date)}
								>
									{isAdmin ? 'Посмотреть работы' : 'Открыть и изменить отчёт'}
								</Button>
							}
							title={row.project_name}
							description={
								<>
									{dayjs(row.date).format('D MMM YYYY')} ·{' '}
									{countLabel(row.positions, 'работа', 'работы', 'работ')}
									{row.crew_count ? ' · ' + row.crew_count + ' чел.' : ''}
								</>
							}
							value={<Money value={row.amount} />}
							meta={<Status status={row.sync_status} />}
							status={['synced', 'imported'].includes(row.sync_status) ? 'sent' : 'pending'}
							leading={
								<span className="compact-date">
									<b>{dayjs(row.date).format('DD')}</b>
									<small>{dayjs(row.date).format('MMM').replace(/\.$/, '')}</small>
								</span>
							}
						>
							<p className="page-context">
								{dayjs(row.date).format('D MMMM YYYY')} · {row.owner_name}
							</p>

							<dl className="report-detail-summary">
								<div>
									<dt>За день</dt>
									<dd>
										<Money value={row.amount} />
									</dd>
								</div>
								<div>
									<dt>Бригада</dt>
									<dd>{row.crew_count ? row.crew_count + ' чел.' : 'Не указана'}</dd>
								</div>
								<div>
									<dt>На человека</dt>
									<dd>{row.crew_count ? <Money value={row.per_person} /> : '—'}</dd>
								</div>
							</dl>
							<Status status={row.sync_status} />
							<HistoryReportDetails project={row.project_id} date={row.date} />
						</CompactWorkEditor>
					))}
				</div>
				{!loading && !data?.rows.length && <Empty description="За выбранный период отчётов нет" />}
			</Spin>
		</>
	);
}
