import { Button, Empty } from 'antd';
import 'dayjs/locale/ru';
import { ArrowDownToLine, ChevronRight, History } from 'lucide-react';
import dayjs from '../lib/date';

import type { WorkspaceView } from '../App';
import { Status } from '../components/SyncStatus';
import { Money } from '../lib/format';
export function ReportsPage({ workspace }: { workspace: WorkspaceView }) {
	const {
		data,
		setPage,
		busy,
		active,
		positions,
		changeDay,
		amount,
		retry,
		showChanges,
		exportCsv,
	} = workspace;
	return (
		<>
			<div className="page-title">
				<div>
					<span className="overline">{active?.name}</span>
					<h1>Отчёты</h1>
				</div>
				<Button icon={<ArrowDownToLine size={17} />} onClick={exportCsv} disabled={!data}>
					CSV
				</Button>
			</div>
			<div className="history-summary">
				<span>
					Всего выполнено
					<strong>
						<Money value={(data?.history || []).reduce((s, h) => s + h.amount, 0)} />
					</strong>
				</span>
				<button onClick={showChanges}>
					<History size={17} />
					Изменения
					<ChevronRight size={14} />
				</button>
			</div>
			<div className="history-list">
				{data?.history.map((h) => (
					<section className="history-card" key={h.date}>
						<button
							className="history-open"
							onClick={() => {
								void changeDay(h.date);
								setPage('today');
							}}
						>
							<div className="history-day">
								<span>{dayjs(h.date).format('DD')}</span>
								<small>{dayjs(h.date).format('MMM')}</small>
							</div>
							<div className="history-main">
								<b>{dayjs(h.date).format('D MMMM YYYY')}</b>
								<small>
									{h.positions} работ
									{h.crew_count ? ` · ${h.crew_count} чел.` : ''}
								</small>
							</div>
							<ChevronRight size={17} />
						</button>
						<div className="history-finance">
							<span>
								За день
								<strong>
									<Money value={h.amount} />
								</strong>
							</span>
							<span>
								На человека
								<strong>
									{h.crew_count ? (
										<Money value={h.per_person} />
									) : (
										<span className="no-value">Не указано</span>
									)}
								</strong>
							</span>
						</div>
						<div className="history-bottom">
							<Status status={h.sync_status} />
							{h.revision > 0 && h.sync_status !== 'synced' && (
								<Button size="small" loading={busy} onClick={() => void retry(h.date)}>
									Отправить
								</Button>
							)}
						</div>
						{h.sync_status === 'error' && h.sync_error && (
							<small className="sync-error">{h.sync_error}</small>
						)}
					</section>
				))}
			</div>
			{!data?.history.length && <Empty description="Отчётов пока нет" />}
		</>
	);
}
