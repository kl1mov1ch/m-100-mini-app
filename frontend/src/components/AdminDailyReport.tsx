import { Button, Empty, Spin } from 'antd';
import { ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useReportDateSwipe } from '../hooks/useReportDateSwipe';
import { DatePicker } from './ResponsiveDatePicker';
import { reportStatus, Status } from './SyncStatus';
import { Money, nf, unit } from '../lib/format';
import { estimateBalance } from '../lib/position-volume';
import { openExternalLink } from '../lib/telegram';
import { request } from '../lib/api';
import { CompactWorkEditor } from './CompactRow';
import { WorkEstimate, WorkOverruns } from './WorkEstimate';
import dayjs from '../lib/date';
import type { WorkspaceView } from '../App';

export function AdminDailyReport({ workspace }: { workspace: WorkspaceView }) {
	const dateSwipe = useReportDateSwipe(workspace);
	const { data, active, day, changeDay, lines, byId, amount, report } = workspace;
	const project =
		active && data?.project?.id === active.id && data.config.source === 'bitrix'
			? active.id
			: undefined;
	const config = project ? data?.config : undefined;
	const knownUrl = [config?.public_url, config?.detail_url].find((url) =>
		url?.startsWith('https://'),
	);
	const [source, setSource] = useState<{ project: string; url: string }>();
	useEffect(() => {
		setSource(undefined);
		if (!project || knownUrl) return;
		const controller = new AbortController();
		void request<{ url: string }>('/object/table/source', undefined, project, controller.signal)
			.then(({ url }) => {
				if (!controller.signal.aborted) setSource({ project, url });
			})
			.catch(() => {
				if (!controller.signal.aborted) setSource({ project, url: '' });
			});
		return () => controller.abort();
	}, [project, knownUrl]);
	if (!active) return <Empty description="Выберите объект" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
	if (!data || data.project?.id !== active.id) return <Spin />;
	const original = knownUrl || (source?.project === project ? source?.url : undefined);
	const current = data.history.find((item) => item.date === day);
	const entries = lines.flatMap((line) => {
		const position = line.item_id ? byId[line.item_id] : undefined;
		return position
			? [{ position, balance: estimateBalance(position, line.quantity, line.quantity) }]
			: [];
	});
	const balances = Object.fromEntries(
		entries.map(({ position, balance }) => [position.id, balance]),
	);
	return (
		<>
			<div className="page-title swipe-surface" {...dateSwipe}>
				<div>
					<span className="overline">{active?.owner_name}</span>
					<h1>{active.name}</h1>
				</div>
				<DatePicker
					aria-label="Дата просмотра отчёта"
					value={dayjs(day)}
					format="DD.MM.YYYY"
					allowClear={false}
					workDates={data.history.map((item) => item.date)}
					onChange={(value) => value && void changeDay(value.format('YYYY-MM-DD'))}
				/>
			</div>
			{data.config.source === 'bitrix' && original && (
				<Button
					href={original}
					onClick={(event) => openExternalLink(event, original)}
					target="_blank"
					rel="noopener noreferrer"
					icon={<ExternalLink size={16} aria-hidden />}
				>
					Исходный Excel в Битрикс24
				</Button>
			)}
			{project && source?.project === project && !original && (
				<p className="table-connection-notice">Ссылка на исходный Excel недоступна.</p>
			)}
			{data.config.object_note && <p className="object-note-read">{data.config.object_note}</p>}
			{report?.day_note && (
				<section className="object-note-read">
					<strong>Примечание за день</strong>
					<div>{report.day_note}</div>
				</section>
			)}
			<section className="report-metrics">
				<div className="metric-primary">
					<span>Выработка за день</span>
					<strong>
						<Money value={amount} />
					</strong>
					<small>{dayjs(day).format('D MMMM YYYY')}</small>
				</div>
				<div>
					<span>Работ за день</span>
					<strong>{lines.length}</strong>
					<small>
						{current?.crew_count ? `${current.crew_count} работников` : 'Бригада не указана'}
					</small>
				</div>
				<div>
					<span>На человека</span>
					<strong>{current?.crew_count ? <Money value={current.per_person} /> : '—'}</strong>
				</div>
				<div>
					<span>Состояние</span>
					<Status
						state={reportStatus(
							current?.sync_status,
							!!current?.positions,
							active.table?.read_connected,
						)}
					/>
				</div>
			</section>
			<WorkOverruns items={entries} confirmed={!!report?.revision} />
			<div className="admin-work-list compact-list">
				{lines.map((line) => {
					const position = line.item_id ? byId[line.item_id] : undefined;
					return (
						<CompactWorkEditor
							key={line.item_id}
							title={position?.name || line.raw || 'Работа'}
							description={
								nf.format(line.quantity || 0) + ' ' + unit(position?.unit || 'ед.') + ' за день'
							}
							value={<Money value={(line.quantity || 0) * (position?.rate || 0)} />}
							meta={
								position && balances[position.id].excess
									? 'Перерасход ' +
										nf.format(balances[position.id].excess) +
										' ' +
										unit(position.unit)
									: position?.section
							}
							attention={!!position && !!balances[position.id].excess}
						>
							<section className="admin-work-row work-detail">
								<b>{position?.name || line.raw}</b>
								<div>
									<span>Стоимость работы</span>
									<strong>
										<Money value={(line.quantity || 0) * (position?.rate || 0)} />
									</strong>
								</div>
								{position && <WorkEstimate balance={balances[position.id]} unit={position.unit} />}
								{line.note && <p className="object-note-read">{line.note}</p>}
								{position && (
									<p className="position-rate">
										<Money value={position.rate} /> / {unit(position.unit)}
									</p>
								)}
								{position?.source_sheet && position.source_row > 0 && (
									<p className="position-rate">
										{position.source_sheet} · строка {position.source_row}
									</p>
								)}
							</section>
						</CompactWorkEditor>
					);
				})}
			</div>
			{!lines.length && (
				<Empty description="За этот день работы не отмечены" image={Empty.PRESENTED_IMAGE_SIMPLE} />
			)}
		</>
	);
}
