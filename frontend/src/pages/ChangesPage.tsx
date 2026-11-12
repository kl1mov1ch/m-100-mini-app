import { Button, Empty } from 'antd';
import { ArrowLeft, ArrowRight } from 'lucide-react';
import { useState } from 'react';
import dayjs from '../lib/date';
import type { WorkspaceView } from '../App';
import { countLabel, nf, unit } from '../lib/format';
import type { Change } from '../types';

const actionLabels: Record<string, string> = {
	project_name_normalized: 'Уточнено название объекта',
	restore_day: 'Возврат к началу дня',
	catalogue_reconciled: 'Обновление сметы',
	catalogue_position_hide: 'Работа скрыта из подбора',
	catalogue_position_show: 'Работа возвращена в подбор',
	catalogue_position_delete: 'Работа удалена из сметы',
};
type CellChange = NonNullable<Change['payload']['table_changes']>[number];
const comparableValue = (value: CellChange['before']) =>
	value == null ? '' : String(value).trim();
const cellValue = (value: CellChange['before']) => comparableValue(value) || 'Пусто';

function SheetChanges({ sheet, rows }: { sheet: string; rows: CellChange[] }) {
	const [limit, setLimit] = useState(20);
	return (
		<details className="change-sheet">
			<summary>
				<span>{sheet}</span>
				<small>{countLabel(rows.length, 'ячейка', 'ячейки', 'ячеек')}</small>
			</summary>
			<div className="change-rows">
				{rows.slice(0, limit).map((row, index) => (
					<div className="change-value-row" key={row.cell + ':' + index}>
						<code>{row.cell}</code>
						<span className="change-before">{cellValue(row.before)}</span>
						<ArrowRight size={14} aria-hidden />
						<strong>{cellValue(row.after)}</strong>
					</div>
				))}
			</div>
			{rows.length > limit && (
				<Button type="text" onClick={() => setLimit((value) => value + 20)}>
					Показать ещё {Math.min(20, rows.length - limit)}
				</Button>
			)}
		</details>
	);
}

export function ChangesPage({ workspace }: { workspace: WorkspaceView }) {
	const { setPage, changes } = workspace;
	return (
		<>
			<div className="page-title">
				<div>
					<button className="back-link" onClick={() => setPage('history')}>
						<ArrowLeft size={16} />
						История
					</button>
					<h1>Изменения объекта</h1>
					<small className="page-context">{workspace.active?.name}</small>
				</div>
			</div>
			<div className="timeline">
				{changes.map((change) => {
					const payload = change.payload;
					const cells = (payload.table_changes || []).filter(
						(row) => comparableValue(row.before) !== comparableValue(row.after),
					);
					const groups = new Map<string, CellChange[]>();
					for (const row of cells) groups.set(row.sheet, [...(groups.get(row.sheet) || []), row]);
					const lines = (payload.changes?.lines || []).filter((line) => line.before !== line.after);
					const crewChanged =
						payload.changes && payload.changes.crew_before !== payload.changes.crew_after;
					return (
						<section className="change-card" key={change.id}>
							<header className="change-heading">
								<strong>
									{actionLabels[payload.action || ''] ||
										(payload.table_changes ? 'Исправления таблицы' : 'Изменение отчёта')}
								</strong>
								<time dateTime={change.created_at}>
									{dayjs(change.created_at).format('D MMMM, HH:mm')}
								</time>
							</header>
							<div className="change-author">
								{payload.actor_name || 'Мастер'}
								{payload.changes ? ' · отчёт за ' + dayjs(change.date).format('D MMMM YYYY') : ''}
							</div>
							{payload.position_name && <p className="change-position">{payload.position_name}</p>}
							{cells.length > 0 && (
								<p className="change-summary">
									{countLabel(
										cells.length,
										'изменённая ячейка',
										'изменённые ячейки',
										'изменённых ячеек',
									)}{' '}
									· {countLabel(groups.size, 'лист', 'листа', 'листов')}
								</p>
							)}
							{[...groups].map(([sheet, rows]) => (
								<SheetChanges key={sheet} sheet={sheet} rows={rows} />
							))}
							{payload.table_changes && !cells.length && (
								<p className="change-note">Значения ячеек не изменились.</p>
							)}
							{lines.length > 0 && (
								<div className="change-report-lines">
									{lines.map((line, index) => (
										<div key={index}>
											<span>{line.name}</span>
											<span>
												<del>{nf.format(line.before)}</del>
												<ArrowRight size={14} aria-hidden />
												<strong>
													{nf.format(line.after)} {unit(line.unit)}
												</strong>
											</span>
										</div>
									))}
								</div>
							)}
							{crewChanged && (
								<div className="change-crew">
									<span>Бригада</span>
									<strong>
										{payload.changes!.crew_before} → {payload.changes!.crew_after} чел.
									</strong>
								</div>
							)}
						</section>
					);
				})}
			</div>
			{!changes.length && <Empty description="Подтверждённых изменений пока нет" />}
		</>
	);
}
