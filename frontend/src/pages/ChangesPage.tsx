import { Empty } from 'antd';
import 'dayjs/locale/ru';
import { ArrowLeft } from 'lucide-react';
import dayjs from '../lib/date';

import type { WorkspaceView } from '../App';
import { nf, unit } from '../lib/format';

const actionLabels: Record<string, string> = {
	restore_day: 'возврат к началу дня',
	catalogue_reconciled: 'обновление сметы',
	catalogue_position_hide: 'работа скрыта из подбора',
	catalogue_position_show: 'работа возвращена в подбор',
	catalogue_position_delete: 'работа удалена из сметы',
};

export function ChangesPage({ workspace }: { workspace: WorkspaceView }) {
	const { setPage, changes } = workspace;
	return (
		<>
			<div className="page-title">
				<div>
					<button className="back-link" onClick={() => setPage('history')}>
						<ArrowLeft size={15} />
						Отчёты
					</button>
					<h1>Изменения</h1>
				</div>
			</div>
			<div className="timeline">
				{changes.map((c) => (
					<section className="change-card" key={c.id}>
						<div>
							<b>{dayjs(c.created_at).format('D MMMM, HH:mm')}</b>
							<small>
								{c.payload.actor_name || 'Мастер'} ·{' '}
								{actionLabels[c.payload.action || ''] ||
									(c.payload.table_changes
										? 'исправления таблицы'
										: 'отчёт ' + dayjs(c.date).format('DD.MM.YYYY'))}
							</small>
						</div>
						{c.payload.position_name && <p>{c.payload.position_name}</p>}
						{c.payload.table_changes?.map((change, index) => (
							<p key={index}>
								<span>
									{change.sheet} · {change.cell}
								</span>
								<strong>
									{String(change.before ?? 'Пусто')} → {String(change.after ?? 'Пусто')}
								</strong>
							</p>
						))}
						{c.payload.changes?.lines.map((l) => (
							<p key={l.name}>
								<span>{l.name}</span>
								<strong>
									{nf.format(l.before)} → {nf.format(l.after)} {unit(l.unit)}
								</strong>
							</p>
						))}
						{c.payload.changes &&
							c.payload.changes.crew_before !== c.payload.changes.crew_after && (
								<p>
									<span>Работников</span>
									<strong>
										{c.payload.changes.crew_before} → {c.payload.changes.crew_after}
									</strong>
								</p>
							)}
					</section>
				))}
			</div>
			{!changes.length && <Empty description="Подтверждённых изменений пока нет" />}
		</>
	);
}
