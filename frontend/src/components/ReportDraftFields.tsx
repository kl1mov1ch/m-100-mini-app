import { Alert, Button, InputNumber, Segmented, Select } from 'antd';
import { LoaderCircle, Trash2, Users } from 'lucide-react';
import type { WorkspaceView } from '../App';
import { Money, unit, countLabel } from '../lib/format';
import './report-draft.css';

export function ReportDraftFields({ workspace }: { workspace: WorkspaceView }) {
	const {
		parsed,
		parsing,
		positions,
		byId,
		patchParsedLine,
		removeParsedLine,
		parsedCrew,
		parsedCrewAmbiguous,
		updateParsedCrew,
		crew,
		report,
		recognizedMode,
		setRecognizedMode,
		confirmParsedReport,
		busy,
	} = workspace;
	if (!parsed.length && !parsedCrew && !parsing) return null;
	const valid =
		parsed.length > 0 &&
		!parsedCrewAmbiguous &&
		parsed.every((line) => line.item_id && line.quantity && line.quantity > 0);
	return (
		<div className="report-draft-fields">
			<div className="draft-status">
				<b>
					{parsed.length
						? `${countLabel(parsed.length, 'работа', 'работы', 'работ')} из сметы`
						: 'Разбираем сообщение'}
				</b>
				{parsing && <LoaderCircle size={16} className="spinning" />}
			</div>
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
			{parsed.map((line, index) => {
				const position = line.item_id ? byId[line.item_id] : null;
				const candidates = positions.filter((item) => (line.candidates || []).includes(item.id));
				const others = positions.filter(
					(item) => !candidates.some((candidate) => candidate.id === item.id),
				);
				const options = (items: typeof positions) =>
					items.map((item) => ({ value: item.id, label: `${item.name} · ${unit(item.unit)}` }));
				return (
					<section
						className={'draft-work ' + (!position || !line.quantity ? 'needs-review' : '')}
						key={index}
					>
						<div className="draft-work-heading">
							<b>{line.raw || `Работа ${index + 1}`}</b>
							<Button
								type="text"
								size="small"
								aria-label={'Убрать распознанную работу ' + (index + 1)}
								icon={<Trash2 size={16} />}
								onClick={() => removeParsedLine(index)}
							/>
						</div>
						<Select
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
						{!position && (
							<small className="draft-review-hint">Выберите подходящую работу из вариантов</small>
						)}
					</section>
				);
			})}
			{!!report?.lines.length && (
				<div className="draft-mode">
					<span>За этот день уже есть отчёт</span>
					<Segmented
						block
						value={recognizedMode}
						onChange={setRecognizedMode}
						options={[
							{ value: 'append', label: 'Добавить работы' },
							{ value: 'replace', label: 'Уточнить итог дня' },
						]}
					/>
				</div>
			)}
			<Button
				block
				type="primary"
				size="large"
				disabled={!valid}
				loading={busy}
				onClick={confirmParsedReport}
			>
				Проверить и отправить
			</Button>
		</div>
	);
}
