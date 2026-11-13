import { Alert, Button, InputNumber, Select } from 'antd';
import { Trash2, Users } from 'lucide-react';
import type { WorkspaceView } from '../App';
import { useConfirmWorkRemoval } from '../hooks/useConfirmWorkRemoval';
import { Money, unit, countLabel, nf } from '../lib/format';
import { estimateBalance } from '../lib/position-volume';
import { WorkEstimate } from './WorkEstimate';
import './report-draft.css';
import { CompactWorkEditor } from './CompactRow';

export function ReportDraftFields({ workspace }: { workspace: WorkspaceView }) {
	const confirmRemoval = useConfirmWorkRemoval();
	const {
		parsed,
		parsing,
		parseNote,
		positions,
		byId,
		patchParsedLine,
		removeParsedLine,
		parsedCrew,
		parsedCrewAmbiguous,
		updateParsedCrew,
		crew,
		report,
		estimateLines,
		lines,
		confirmParsedReport,
		busy,
	} = workspace;
	if (!parsed.length) {
		return !parsing && parseNote ? (
			<div className="report-draft-fields">
				<Alert type="warning" showIcon message={parseNote} />
			</div>
		) : null;
	}
	const valid =
		parsed.length > 0 &&
		!parsedCrewAmbiguous &&
		parsed.every((line) => line.item_id && line.quantity && line.quantity > 0);
	const daily = new Map<string, number>();
	for (const line of [...lines, ...parsed]) {
		if (line.item_id)
			daily.set(line.item_id, (daily.get(line.item_id) || 0) + (line.quantity || 0));
	}
	return (
		<div className="report-draft-fields">
			<div className="draft-status">
				<b>{countLabel(parsed.length, 'работа', 'работы', 'работ')} из сметы</b>
			</div>
			{parseNote && <Alert type="warning" showIcon message={parseNote} />}
			{parsedCrewAmbiguous && (
				<Alert type="warning" showIcon message="Уточните количество работников" />
			)}
			<label className="draft-crew">
				<span>
					<Users size={17} /> Работников
				</span>
				<InputNumber
					aria-label="Работников в распознанном отчёте"
					min={1}
					max={1000}
					precision={0}
					value={parsedCrew || crew}
					onChange={updateParsedCrew}
				/>
			</label>
			<div className="compact-list">
				{parsed.map((line, index) => {
					const position = line.item_id ? byId[line.item_id] : null;
					const balance = position
						? estimateBalance(position, estimateLines[position.id], daily.get(position.id))
						: null;
					const candidates = positions.filter((item) => (line.candidates || []).includes(item.id));
					const others = positions.filter(
						(item) => !candidates.some((candidate) => candidate.id === item.id),
					);
					const options = (items: typeof positions) =>
						items.map((item) => ({ value: item.id, label: `${item.name} · ${unit(item.unit)}` }));
					return (
						<CompactWorkEditor
							key={(line.raw || line.item_id || 'work') + ':' + index}
							title={position?.name || line.raw || 'Работа ' + (index + 1)}
							description={
								<>
									{line.quantity == null
										? 'Уточните объём'
										: nf.format(line.quantity) +
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
							hint="Правки остаются в черновике до подтверждения отчёта."
						>
							<section className="draft-work work-detail">
								<div className="draft-work-heading">
									<b>{line.raw || `Работа ${index + 1}`}</b>
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
								<Select
									virtual={false}
									classNames={{ popup: { root: 'work-position-options' } }}
									aria-label={'Позиция сметы для работы ' + (index + 1)}
									showSearch
									optionFilterProp="label"
									placeholder="Выберите вариант из сметы"
									value={line.item_id || undefined}
									onChange={(value) => patchParsedLine(index, { item_id: value, reason: '' })}
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
											min={0.01}
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
								{!position && (
									<small className="draft-review-hint">
										Выберите подходящую работу из вариантов
									</small>
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
		</div>
	);
}
