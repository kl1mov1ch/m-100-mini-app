import { Button, InputNumber, Select } from 'antd';
import { Pencil, Trash2, Users } from 'lucide-react';
import { forwardRef, useEffect, useImperativeHandle, useState } from 'react';
import { ReportConfirmation } from '../ReportConfirmation';
import { useConfirmWorkRemoval } from '../hooks/useConfirmWorkRemoval';
import { calculateAmount, mergeWorkQuantities } from '../lib/calculation';
import { countLabel, Money, nf, unit } from '../lib/format';
import type { Position, Report } from '../types';
import './review-editor.css';

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
	onValidityChange: (valid: boolean) => void;
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
		useEffect(() => props.onValidityChange(valid), [valid]);
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
		const exceeds = Object.entries(quantities).some(
			([id, quantity]) => quantity! > (props.positions[id]?.remaining || 0) + (before[id] || 0),
		);
		const rows = [...new Set([...Object.keys(before), ...Object.keys(quantities)])];
		const workContent = (
			<div className="review-editor">
				<p className="review-editor-hint">
					Все работы объединены. Здесь можно изменить объёмы, состав работ и бригаду.
				</p>
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
				{rows.map((id) => {
					const position = props.positions[id];
					if (!position) return null;
					const previous = before[id] || 0;
					const next = quantities[id] ?? (id in quantities ? null : 0);
					return (
						<section className={'review-editor-work ' + (next === 0 ? 'removed' : '')} key={id}>
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
						</section>
					);
				})}
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
				exceeds={exceeds}
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
