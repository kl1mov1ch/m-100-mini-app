import { Button, InputNumber, Select } from 'antd';
import { Pencil, Trash2, Users } from 'lucide-react';
import { forwardRef, useEffect, useImperativeHandle, useState } from 'react';
import { ReportConfirmation } from '../ReportConfirmation';
import { useConfirmWorkRemoval } from '../hooks/useConfirmWorkRemoval';
import { calculateAmount, mergeWorkQuantities } from '../lib/calculation';
import { countLabel, Money, nf, unit } from '../lib/format';
import type { Position, Report } from '../types';
import { estimateBalance } from '../lib/position-volume';
import { WorkEstimate, WorkOverruns } from './WorkEstimate';
import './review-editor.css';
import { CompactWorkEditor } from './CompactRow';

export type ReportReviewValues = {
	lines: { item_id: string; quantity: number }[];
	crew_count: number;
};
export type ReportReviewHandle = { getValues: () => ReportReviewValues };
type ReviewProps = {
	report: Report;
	positions: Record<string, Position>;
	lines: { item_id: string; quantity: number }[];
	crew: number;
	connected: boolean;
	estimateLines: Record<string, number | null>;
	onValidityChange: (valid: boolean, exceeds: boolean) => void;
};

export const ReportReviewEditor = forwardRef<ReportReviewHandle, ReviewProps>(
	function ReportReviewEditor(props, ref) {
		const confirmRemoval = useConfirmWorkRemoval();
		const [quantities, setQuantities] = useState<Record<string, number | null>>(() =>
			Object.fromEntries(props.lines.map((line) => [line.item_id, line.quantity])),
		);
		const [crew, setCrew] = useState<number | null>(props.crew);
		const [editing, setEditing] = useState<string | null>(null);
		const before = Object.fromEntries(
			props.report.lines.map((line) => [line.item_id!, line.quantity]),
		);
		const valid =
			!!crew &&
			Number.isInteger(crew) &&
			crew >= 1 &&
			crew <= 1000 &&
			(props.report.revision > 0 ||
				props.report.lines.length > 0 ||
				Object.values(quantities).some((value) => value! > 0)) &&
			Object.values(quantities).every(
				(value) => value !== null && Number.isFinite(value) && value >= 0 && value <= 1e8,
			);
		useImperativeHandle(ref, () => ({
			getValues: () => {
				if (!valid) throw new Error('Проверьте объёмы и количество работников');
				return {
					lines: Object.entries(quantities)
						.filter(([, quantity]) => quantity! > 0)
						.map(([item_id, quantity]) => ({ item_id, quantity: quantity! })),
					crew_count: crew!,
				};
			},
		}));
		const changeQuantity = (id: string, value: number | null) =>
			setQuantities((current) => ({ ...current, [id]: value }));
		const moveWork = (from: string, to: string) => {
			setQuantities((current) => {
				if (from === to) return current;
				const moved = mergeWorkQuantities([
					{ item_id: to, quantity: current[to] || 0 },
					{ item_id: to, quantity: current[from] || 0 },
				])[0].quantity;
				return { ...current, [from]: 0, [to]: moved };
			});
			setEditing(null);
		};
		const options = Object.values(props.positions)
			.filter((position) => !position.hidden)
			.map((position) => ({
				value: position.id,
				label: `${position.name} · ${unit(position.unit)}`,
			}));
		const amount = calculateAmount(
			Object.entries(quantities).map(([id, quantity]) => ({
				quantity,
				rate: props.positions[id]?.rate || 0,
			})),
		);
		const rows = [...new Set([...Object.keys(before), ...Object.keys(quantities)])];
		const balances = Object.fromEntries(
			rows.flatMap((id) => {
				const position = props.positions[id];
				return position
					? [[id, estimateBalance(position, props.estimateLines[id], quantities[id])] as const]
					: [];
			}),
		);
		const overrunItems = rows
			.filter((id) => quantities[id] && balances[id]?.excess)
			.map((id) => ({ position: props.positions[id], balance: balances[id] }));
		useEffect(
			() => props.onValidityChange(valid, !!overrunItems.length),
			[valid, !!overrunItems.length],
		);
		const workContent = (
			<div className="review-editor">
				<WorkOverruns items={overrunItems} />
				<label className="review-editor-crew">
					<span>
						<Users size={16} /> Работников
					</span>
					<InputNumber
						aria-label="Работников в общем отчёте"
						min={1}
						max={1000}
						precision={0}
						value={crew}
						onChange={setCrew}
					/>
				</label>
				<div className="compact-list">
					{rows.map((id) => {
						const position = props.positions[id];
						if (!position) return null;
						const previous = before[id] || 0;
						const next = quantities[id] ?? (id in quantities ? null : 0);
						return (
							<CompactWorkEditor
								key={id}
								title={position.name}
								description={
									'Было ' +
									nf.format(previous) +
									' → ' +
									(next == null ? 'Уточните объём' : nf.format(next) + ' ' + unit(position.unit))
								}
								value={<Money value={(next || 0) * position.rate} />}
								meta={
									next === 0
										? 'Будет убрано'
										: balances[id]?.excess
											? 'Перерасход ' + nf.format(balances[id].excess) + ' ' + unit(position.unit)
											: next !== previous
												? 'Изменено'
												: 'Без изменений'
								}
								attention={next == null || !!balances[id]?.excess}
								hint="Правки применятся при подтверждении отчёта."
							>
								<section className="review-editor-work work-detail">
									<div className="review-editor-heading">
										<b>{position.name}</b>
										<Button
											type="text"
											size="small"
											aria-label={'Убрать из общего отчёта ' + position.name}
											icon={<Trash2 size={16} />}
											disabled={next === 0}
											onClick={() =>
												confirmRemoval(
													{
														name: position.name,
														quantity: next,
														unit: position.unit,
														saved: previous > 0,
													},
													() => changeQuantity(id, 0),
												)
											}
										/>
									</div>
									<div className="review-editor-comparison">
										<span>
											Было {nf.format(previous)} {unit(position.unit)}
											{next !== null && next !== previous
												? ` · ${next > previous ? '+' : ''}${nf.format(next - previous)} ${unit(position.unit)}`
												: ''}
										</span>
										<b>
											{next === 0
												? 'Будет убрано'
												: next === null
													? 'Укажите объём'
													: `Итого ${nf.format(next)} ${unit(position.unit)}`}
										</b>
									</div>
									<div className="review-editor-values">
										<label>
											Итоговый объём
											<InputNumber
												aria-label={'Итоговый объём ' + position.name}
												min={0}
												max={1e8}
												controls={false}
												value={next}
												onChange={(value) => changeQuantity(id, value)}
												addonAfter={unit(position.unit)}
											/>
										</label>
										<div>
											<span>Сумма</span>
											<strong>
												<Money value={(next || 0) * position.rate} />
											</strong>
										</div>
									</div>
									<WorkEstimate balance={balances[id]} unit={position.unit} />
									{editing === id ? (
										<Select<string>
											autoFocus
											virtual={false}
											classNames={{ popup: { root: 'work-position-options' } }}
											aria-label="Заменить работу в общем отчёте"
											showSearch
											optionFilterProp="label"
											value={id}
											options={options}
											onChange={(value) => moveWork(id, value)}
										/>
									) : (
										<Button
											type="link"
											size="small"
											icon={<Pencil size={12} />}
											onClick={() => setEditing(id)}
										>
											Изменить работу
										</Button>
									)}
									<p className="position-rate">
										<Money value={position.rate} /> / {unit(position.unit)}
									</p>
								</section>
							</CompactWorkEditor>
						);
					})}
				</div>
				<Select<string>
					virtual={false}
					classNames={{ popup: { root: 'work-position-options' } }}
					aria-label="Добавить работу в общий отчёт"
					showSearch
					optionFilterProp="label"
					placeholder="Добавить работу из сметы"
					value={undefined}
					options={options.filter((option) => !(quantities[option.value]! > 0))}
					onChange={(value) => changeQuantity(value, null)}
				/>
			</div>
		);
		return (
			<ReportConfirmation
				date={props.report.date}
				positions={props.positions}
				before={before}
				after={quantities}
				crewBefore={props.report.crew_count}
				crewAfter={crew || 1}
				amountBefore={props.report.payroll.amount}
				amountAfter={amount}
				connected={props.connected}
				exceeds={false}
				renderMoney={(value) => <Money value={value} />}
				workContent={workContent}
				crewContent={null}
				workSummary={
					countLabel(
						Object.values(quantities).filter((value) => value! > 0).length,
						'работа',
						'работы',
						'работ',
					) + ' · можно редактировать'
				}
			/>
		);
	},
);
