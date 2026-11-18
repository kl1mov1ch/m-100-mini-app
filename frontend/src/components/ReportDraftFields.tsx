import { sortSearchOptions } from '../lib/search';
import { Alert, InputNumber } from 'antd';
import { Select } from './Select';
import { Button } from './Button';
import { Trash2 } from 'lucide-react';
import { ChevronRight } from './kit-icons';
import type { WorkspaceView } from '../App';
import { useConfirmWorkRemoval } from '../hooks/useConfirmWorkRemoval';
import { Money, unit, countLabel, nf } from '../lib/format';
import { estimateBalance } from '../lib/position-volume';
import { WorkEstimate } from './WorkEstimate';
import './report-draft.css';
import { CompactWorkEditor } from './CompactRow';
import { ProjectMatchHint } from './ProjectMatchHint';

const lengthFactors: Record<string, number> = { м: 1, км: 1000, см: 0.01, мм: 0.001 };
const volumeFormat = new Intl.NumberFormat('ru-BY', { maximumFractionDigits: 9 });

function measureKey(value: string) {
	const label = unit(value.trim()).toLocaleLowerCase('ru').replace(/\.$/, '');
	if (/^штук[аи]?$/.test(label)) return 'шт';
	return label.replace('²', '2').replace('³', '3');
}

function selectedQuantity(
	quantity: number | null,
	source: string | null | undefined,
	target: string,
) {
	if (quantity == null || !source) return quantity;
	const sourceKey = measureKey(source),
		targetKey = measureKey(target);
	if (sourceKey === targetKey) return quantity;
	const from = lengthFactors[sourceKey],
		to = lengthFactors[targetKey];
	if (!from || !to) return null;
	const converted = Number(((quantity * from) / to).toPrecision(15));
	return converted > 0 && converted <= 1e8 ? converted : null;
}

export function ReportDraftFields({
	workspace,
	showSubmit = true,
	onProjectMatch,
}: {
	workspace: WorkspaceView;
	showSubmit?: boolean;
	onProjectMatch?: (id: string) => void;
}) {
	const confirmRemoval = useConfirmWorkRemoval();
	const {
		parsed,
		parsing,
		parseNote,
		positions,
		byId,
		patchParsedLine,
		removeParsedLine,
		parsedCrewAmbiguous,
		parsedIncomplete,
		report,
		estimateLines,
		lines,
		confirmParsedReport,
		busy,
		projectMatch,
		dismissProjectMatch,
		switchForWork,
	} = workspace;
	if (!parsed.length) {
		return !parsing && parseNote ? (
			<div className="report-draft-fields">
				<Alert type="warning" showIcon message={parseNote} />
			</div>
		) : null;
	}
	const valid = !parsedCrewAmbiguous && parsedIncomplete === 0;
	const daily = new Map<string, number>();
	for (const line of [...lines, ...parsed]) {
		if (line.item_id)
			daily.set(line.item_id, (daily.get(line.item_id) || 0) + (line.quantity || 0));
	}
	return (
		<div className="report-draft-fields">
			{projectMatch && !parsing && (
				<ProjectMatchHint
					match={projectMatch}
					onSwitch={onProjectMatch ?? ((id) => switchForWork(id))}
					onDismiss={dismissProjectMatch}
				/>
			)}
			<div className="draft-status">
				<b>{countLabel(parsed.length, 'позиция', 'позиции', 'позиций')} к проверке</b>
				{parsing ? (
					<span role="status">Уточняем варианты…</span>
				) : (
					parsedIncomplete > 0 && <span>Уточнить: {parsedIncomplete}</span>
				)}
			</div>
			{parseNote && <Alert type="warning" showIcon message={parseNote} />}
			<div className="compact-list">
				{parsed.map((line, index) => {
					const position = line.item_id ? byId[line.item_id] : null;
					const balance = position
						? estimateBalance(position, estimateLines[position.id], daily.get(position.id))
						: null;
					const candidates = (line.candidates || [])
						.map((id) => byId[id])
						.filter((item) => item && !item.hidden && !item.extra);
					const others = positions.filter(
						(item) => !candidates.some((candidate) => candidate.id === item.id),
					);
					const options = (items: typeof positions) =>
						items.map((item) => ({ value: item.id, label: `${item.name} · ${unit(item.unit)}` }));
					const selectPosition = (id: string) => {
						const next = byId[id];
						patchParsedLine(index, {
							item_id: id,
							reason: '',
							quantity: selectedQuantity(line.quantity, line.unit, next.unit),
							unit: next.unit,
						});
					};
					return (
						<CompactWorkEditor
							key={(line.raw || line.item_id || 'work') + ':' + index}
							title={position?.name || line.raw || 'Работа ' + (index + 1)}
							modalTitle={position ? undefined : 'Выберите работу из сметы'}
							modalClassName="draft-work-editor"
							description={
								<>
									{line.quantity == null
										? 'Уточните объём'
										: volumeFormat.format(line.quantity) +
											' ' +
											unit(position?.unit || line.unit || 'ед.')}{' '}
									· {position ? 'Из сметы' : 'Выберите позицию'}
								</>
							}
							value={position ? <Money value={position.rate * (line.quantity || 0)} /> : '—'}
							meta={
								!position || !line.quantity
									? 'Нужна проверка'
									: balance?.excess
										? 'Перерасход ' + nf.format(balance.excess) + ' ' + unit(position.unit)
										: 'Распознано'
							}
							attention={!position || !line.quantity || !!balance?.excess}
						>
							<section className="draft-work work-detail">
								<div className="draft-work-heading">
									{line.raw && <span>{line.raw}</span>}
									<Button
										type="text"
										size="small"
										aria-label={'Убрать распознанную работу ' + (index + 1)}
										icon={<Trash2 size={16} />}
										onClick={() =>
											confirmRemoval(
												{
													name: position?.name || line.raw || 'Работа',
													quantity: line.quantity,
													unit: position?.unit || line.unit || undefined,
												},
												() => removeParsedLine(index),
											)
										}
									/>
								</div>
								{!position && line.reason && (
									<small className="draft-review-hint">{line.reason}</small>
								)}
								{!position && candidates.length > 0 && (
									<div className="draft-suggestions">
										<strong>Похожие работы</strong>
										{candidates.slice(0, 3).map((item) => (
											<button type="button" key={item.id} onClick={() => selectPosition(item.id)}>
												<span>
													<b>{item.name}</b>
													<small>
														{unit(item.unit)} · <Money value={item.rate} /> / {unit(item.unit)}
													</small>
												</span>
												<ChevronRight size={16} aria-hidden />
											</button>
										))}
									</div>
								)}
								<Select
									classNames={{ popup: { root: 'work-position-options' } }}
									aria-label={'Позиция сметы для работы ' + (index + 1)}
									showSearch
									filterOption={false}
									filterSort={sortSearchOptions}
									placeholder="Найти в смете"
									value={line.item_id || undefined}
									onChange={selectPosition}
									options={[
										...(candidates.length
											? [{ label: 'Подходящие варианты', options: options(candidates) }]
											: []),
										{ label: 'Все работы объекта', options: options(others) },
									]}
								/>
								<div className="draft-work-values">
									<label>
										Объём
										<InputNumber
											aria-label={'Распознанный объём работы ' + (index + 1)}
											controls={false}
											min={0}
											max={1e8}
											value={line.quantity}
											onChange={(value) => patchParsedLine(index, { quantity: value })}
											addonAfter={unit(position?.unit || line.unit || 'ед.')}
										/>
									</label>
									<div>
										<span>Сумма</span>
										<strong>
											{position ? <Money value={position.rate * (line.quantity || 0)} /> : '—'}
										</strong>
									</div>
								</div>
								{position && balance && (
									<>
										<WorkEstimate balance={balance} unit={position.unit} />
										<p className="position-rate">
											<Money value={position.rate} /> / {unit(position.unit)}
										</p>
									</>
								)}
							</section>
						</CompactWorkEditor>
					);
				})}
			</div>
			{!!report?.lines.length && (
				<p className="draft-addition-hint">
					Новые объёмы прибавятся к текущим. Общий итог можно изменить перед отправкой.
				</p>
			)}
			{showSubmit && (
				<Button
					block
					type="primary"
					size="large"
					disabled={
						!valid || parsing || workspace.audioInput.recording || workspace.audioInput.pending
					}
					loading={busy}
					onClick={confirmParsedReport}
				>
					Проверить и отправить
				</Button>
			)}
		</div>
	);
}
