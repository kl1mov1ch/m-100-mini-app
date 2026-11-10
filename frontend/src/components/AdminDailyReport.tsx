import { Button, Empty, Spin } from 'antd';
import { History } from 'lucide-react';
import { DatePicker } from './ResponsiveDatePicker';
import { Status } from './SyncStatus';
import { Money, nf, unit } from '../lib/format';
import dayjs from '../lib/date';
import type { WorkspaceView } from '../App';

export function AdminDailyReport({ workspace }: { workspace: WorkspaceView }) {
	const { data, active, day, changeDay, lines, byId, amount, report, setPage } = workspace;
	if (!data) return <Spin />;
	const current = data.history.find((item) => item.date === day);
	return (
		<>
			<div className="page-title">
				<div>
					<span className="overline">{active?.owner_name}</span>
					<h1>Отчёт</h1>
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
			<section className="report-metrics">
				<div className="metric-primary">
					<span>{active?.name}</span>
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
					<small>По данным мастера</small>
				</div>
				<div>
					<span>Состояние</span>
					<Status status={report?.sync_status || 'local'} />
					<small>Просмотр без изменения</small>
				</div>
			</section>
			<Button block icon={<History size={17} />} onClick={() => setPage('history')}>
				История объекта и выгрузка
			</Button>
			<div className="admin-work-list">
				{lines.map((line) => {
					const position = line.item_id ? byId[line.item_id] : undefined;
					return (
						<section key={line.item_id} className="admin-work-row">
							<b>{position?.name || line.raw}</b>
							<div>
								<span>
									{nf.format(line.quantity || 0)} {unit(position?.unit || '')}
								</span>
								<strong>
									<Money value={(line.quantity || 0) * (position?.rate || 0)} />
								</strong>
							</div>
						</section>
					);
				})}
			</div>
			{!lines.length && <Empty description="За этот день работы не отмечены" />}
		</>
	);
}
