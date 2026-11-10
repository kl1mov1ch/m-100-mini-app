import { Alert, Button, Checkbox, Collapse, Segmented, Select, Tag } from 'antd';
import { Sparkles, TriangleAlert } from 'lucide-react';
import dayjs from '../lib/date';
import { Money, nf, unit } from '../lib/format';
import type { CatalogueReconciliation as Reconciliation, Position } from '../types';
import './reconciliation.css';

type ReconciliationProps = {
	plan: Reconciliation;
	positions: Position[];
	selected: Record<string, string | null>;
	onSelect: (id: string, value: string | null) => void;
	accepted: boolean;
	onAccept: (value: boolean) => void;
	busy: boolean;
	onResolve: () => void;
	dayResolutions: Record<string, string>;
	onResolveDay: (day: string, value: string) => void;
};

export function CatalogueReconciliation(props: ReconciliationProps) {
	const { plan, positions, selected } = props;
	return (
		<div className="reconciliation-panel">
			<Alert
				type="info"
				showIcon
				message="Обновляем смету этого объекта"
				description={plan.notice}
			/>
			{plan.rows.some((row) => !row.selected_id) && (
				<Button block icon={<Sparkles size={16} />} loading={props.busy} onClick={props.onResolve}>
					Подобрать работы с ИИ
				</Button>
			)}
			{plan.rows
				.filter((row) => row.changed)
				.map((row) => {
					const old = row.previous;
					const selectedId = selected[old.id];
					const next = positions.find((position) => position.id === selectedId);
					return (
						<section
							className={
								'reconciliation-row ' + (!next || row.method === 'ai' ? 'needs-review' : '')
							}
							key={old.id}
						>
							<div className="reconciliation-heading">
								<TriangleAlert size={16} />
								<b>{old.name}</b>
								{row.method === 'ai' && <Tag color="gold">Предложил ИИ</Tag>}
							</div>
							<small>
								{old.source_sheet || 'Смета'} · строка {old.source_row} · {unit(old.unit)}
							</small>
							<p>
								{next && row.method !== 'ai'
									? 'Проверьте название, единицу и расценку'
									: row.reason}
							</p>
							<label>Работа в актуальной смете</label>
							<Select
								showSearch
								allowClear={!row.required}
								optionFilterProp="label"
								placeholder={
									row.required
										? 'Выберите работу — она есть в отчётах'
										: 'Можно убрать: в отчётах не используется'
								}
								value={selectedId || undefined}
								onChange={(value) => props.onSelect(old.id, value || null)}
								options={positions
									.filter(
										(position) => position.unit.replace(/\.$/, '') === old.unit.replace(/\.$/, ''),
									)
									.map((position) => ({
										value: position.id,
										label: `${position.name} · ${unit(position.unit)} · строка ${position.source_row}`,
										disabled: Object.entries(selected).some(
											([oldId, newId]) => oldId !== old.id && newId === position.id,
										),
									}))}
							/>
							{next && (
								<div className="reconciliation-values">
									<span>
										Строка{' '}
										<b>
											{old.source_row} → {next.source_row}
										</b>
									</span>
									<span>
										Расценка{' '}
										<b>
											<Money value={old.rate} /> → <Money value={next.rate} />
										</b>
									</span>
									<span>
										План{' '}
										<b>
											{nf.format(old.planned)} → {nf.format(next.planned)} {unit(next.unit)}
										</b>
									</span>
								</div>
							)}
						</section>
					);
				})}
			{!!plan.report_conflicts.length && (
				<section className="reconciliation-row needs-review">
					<b>Отчёты отличаются от таблицы</b>
					<p>
						Проверьте разницу и выберите, какие объёмы сохранить. Расчёты обновятся после
						подтверждения.
					</p>
					<Collapse
						ghost
						defaultActiveKey={
							plan.report_conflicts.length === 1 ? [plan.report_conflicts[0].date] : []
						}
						items={plan.report_conflicts.map((report) => ({
							key: report.date,
							label: dayjs(report.date).format('D MMMM YYYY'),
							children: (
								<div className="reconciliation-day">
									{report.lines.map((line) => (
										<div className="reconciliation-day-line" key={line.item_id}>
											<b>{line.name}</b>
											<span>
												В отчёте {nf.format(line.local)} {unit(line.unit)} · в таблице{' '}
												{nf.format(line.remote)} {unit(line.unit)}
											</span>
										</div>
									))}
									<Segmented
										block
										value={props.dayResolutions[report.date] || 'report'}
										onChange={(value) => props.onResolveDay(report.date, value)}
										options={[
											{ label: 'Сохранить отчёт', value: 'report' },
											{ label: 'Принять таблицу', value: 'table' },
										]}
									/>
								</div>
							),
						}))}
					/>
				</section>
			)}
			<Checkbox checked={props.accepted} onChange={(event) => props.onAccept(event.target.checked)}>
				Изменения проверены. Обновить смету и выбранные отчёты.
			</Checkbox>
		</div>
	);
}
