import { Alert, App, Button, Input, InputNumber, Modal, Select, Tabs, Tag } from 'antd';
import { Check, FileSpreadsheet, Search, Settings2, Sparkles, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { WorkspaceView } from '../App';
import dayjs from '../lib/date';
import { Money, nf, unit } from '../lib/format';
import type {
	CatalogueReconciliation as Reconciliation,
	ImportWarning,
	Position,
	TableFixPayload,
} from '../types';
import { request } from '../lib/api';
import { CatalogueReconciliation } from './CatalogueReconciliation';
import { DatePicker } from './ResponsiveDatePicker';
import './table-import.css';

type CellSuggestions = Record<
	string,
	{ options: { value: string | number; reason: string }[]; message: string; restore_count?: number }
>;

export function TableImportModal({ workspace }: { workspace: WorkspaceView }) {
	const {
		preview,
		setPreview,
		mapping,
		setMapping,
		ack,
		setAck,
		busy,
		reviewImport,
		commitImport,
		applyImportChanges,
		data,
		openObjectSection,
	} = workspace;
	const { message, modal } = App.useApp();
	const [positionMatches, setPositionMatches] = useState<Record<string, string | null>>({});
	const [reconciliationAccepted, setReconciliationAccepted] = useState(false);
	const [resolving, setResolving] = useState(false);
	const [dayResolutions, setDayResolutions] = useState<Record<string, string>>({});
	const [tab, setTab] = useState('issues');
	const [query, setQuery] = useState('');
	const [values, setValues] = useState<Record<string, string | number | null>>({});
	const [strategies, setStrategies] = useState<Record<string, string>>({});
	const [replacementDates, setReplacementDates] = useState<Record<string, string>>({});
	const [editing, setEditing] = useState<string | null>(null);
	const [suggestions, setSuggestions] = useState<CellSuggestions>({});
	const [suggestionError, setSuggestionError] = useState('');
	const [suggestionAttempt, setSuggestionAttempt] = useState(0);
	const hasImportWarnings = Boolean(
		preview?.warnings.some((warning) => warning.severity !== 'info'),
	);
	useEffect(() => {
		setSuggestions({});
		setSuggestionError('');
		if (!preview?.warnings.some((warning) => warning.cell && warning.field)) return;
		const controller = new AbortController();
		request<CellSuggestions>(
			'/imports/consult',
			{ token: preview.token, sheets: preview.sheets },
			workspace.project,
			controller.signal,
		)
			.then((result) => {
				if (!controller.signal.aborted) setSuggestions(result);
			})
			.catch((error: Error) => {
				if (!controller.signal.aborted) setSuggestionError(error.message);
			});
		return () => controller.abort();
	}, [preview, workspace.project, suggestionAttempt]);
	useEffect(() => {
		setTab(
			hasImportWarnings
				? 'issues'
				: preview?.reconciliation?.needs_confirmation
					? 'reconciliation'
					: 'positions',
		);
		setQuery('');
		setValues({});
		setEditing(null);
	}, [preview?.token, hasImportWarnings]);
	useEffect(() => {
		setPositionMatches(
			Object.fromEntries(
				(preview?.reconciliation?.rows || []).map((row) => [row.previous.id, row.selected_id]),
			),
		);
		setReconciliationAccepted(false);
		setDayResolutions({});
	}, [preview]);
	if (!preview) return null;
	const reconciliation = preview.reconciliation;
	const reconciliationPending =
		!!reconciliation?.needs_confirmation &&
		(!reconciliationAccepted ||
			reconciliation.rows.some((row) => row.required && !positionMatches[row.previous.id]) ||
			reconciliation.report_conflicts.some((report) => !dayResolutions[report.date]));
	const resolveReconciliation = async () => {
		setResolving(true);
		try {
			const plan = await request<Reconciliation>(
				'/imports/resolve',
				{ token: preview.token, sheets: mapping },
				workspace.project,
			);
			setPreview({ ...preview, reconciliation: plan });
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setResolving(false);
		}
	};
	const problems = preview.warnings.filter((warning) => warning.severity !== 'info');
	const positions = preview.positions.filter((position) =>
		`${position.name} ${position.source_row}`.toLowerCase().includes(query.toLowerCase()),
	);
	const setValue = (key: string, value: string | number | null) =>
		setValues((current) => ({ ...current, [key]: value }));
	const fixCell = (warning: ImportWarning, value: string | number | null) => {
		if (warning.sheet && warning.cell)
			void applyImportChanges({ edits: [{ sheet: warning.sheet, cell: warning.cell, value }] });
	};
	const fixDailyColumn = (warning: ImportWarning, strategy: 'zero' | 'remove' | 'restore') => {
		const { sheet, column, date } = warning;
		if (!sheet || !column || !date) return;
		const action = {
			zero: ['Заполнить нулями?', 'Пустые и нечисловые объёмы станут нулями.'],
			remove: ['Убрать колонку?', 'Дата и её объёмы исчезнут с листа.'],
			restore: ['Восстановить объёмы?', 'Заполним ячейки по сохранённым данным за эту дату.'],
		}[strategy];
		modal.confirm({
			title: action[0],
			content: `${sheet} · ${column} · ${dayjs(date).format('DD.MM.YYYY')}. ${action[1]}`,
			okText: 'Применить',
			cancelText: 'Отмена',
			onOk: () => applyImportChanges({ daily_columns: [{ sheet, column, date, strategy }] }),
		});
	};
	const savePosition = (position: Position) => {
		const sheet = mapping.find((sheet) => sheet.name === position.source_sheet);
		if (!sheet) return;
		const changes: NonNullable<TableFixPayload['edits']> = [];
		for (const field of ['rate', 'planned', 'unit'] as const) {
			const key = position.id + ':' + field;
			const column = sheet.mapping[field];
			if (column && values[key] !== undefined) {
				let number = column;
				let letter = '';
				while (number > 0) {
					number--;
					letter = String.fromCharCode(65 + (number % 26)) + letter;
					number = Math.floor(number / 26);
				}
				changes.push({ sheet: sheet.name, cell: letter + position.source_row, value: values[key] });
			}
		}
		if (changes.length) void applyImportChanges({ edits: changes });
		setEditing(null);
	};
	const issueCards = (
		<div className="import-issue-list">
			{!problems.length && (
				<Alert
					type="success"
					showIcon
					message="Неоднозначностей нет. Таблица готова к подтверждению."
				/>
			)}
			{problems.map((warning) => {
				const suggestion = suggestions[warning.id];
				if (warning.affected_rows?.length)
					return (
						<section className="table-issue" key={warning.id}>
							<div className="table-issue-title">
								<TriangleAlert size={16} />
								<b>{warning.message}</b>
							</div>
							<small>
								{warning.sheet} · {warning.cell}
								{warning.date && ` · ${dayjs(warning.date).format('DD.MM')}`}
							</small>
							{suggestion?.restore_count === 0 ? (
								<p className="table-issue-help">Нет сохранённых объёмов за эту дату.</p>
							) : suggestion?.restore_count &&
							  suggestion.restore_count < warning.affected_rows.length ? (
								<p className="table-issue-help">
									Можно восстановить {suggestion.restore_count} из {warning.affected_rows.length}{' '}
									ячеек.
								</p>
							) : (
								warning.ai_tip && <p className="table-issue-help">{warning.ai_tip}</p>
							)}
							<div className="table-column-actions">
								<Button
									size="small"
									disabled={suggestion?.restore_count === 0}
									loading={busy}
									type="primary"
									icon={<Sparkles size={14} />}
									onClick={() => fixDailyColumn(warning, 'restore')}
								>
									Восстановить по отчёту
								</Button>
								<Button size="small" loading={busy} onClick={() => fixDailyColumn(warning, 'zero')}>
									Заполнить нулями
								</Button>
								<Button
									size="small"
									loading={busy}
									danger
									onClick={() => fixDailyColumn(warning, 'remove')}
								>
									Убрать колонку
								</Button>
							</div>
						</section>
					);
				const singularCell = warning.cell && /^[A-Z]+\d+$/.test(warning.cell);
				return (
					<section
						className={'table-issue ' + (ack.includes(warning.id) ? 'acknowledged' : '')}
						key={warning.id}
					>
						<div className="table-issue-title">
							<TriangleAlert size={16} />
							<b>{warning.field || 'Проверка данных'}</b>
							{warning.cell && <code>{warning.cell}</code>}
						</div>
						<div className="table-issue-location">
							{warning.sheet && `Лист «${warning.sheet}»`}
							{warning.row && ` · строка ${warning.row}`}
							{warning.column && ` · столбец ${warning.column}`}
						</div>
						{warning.position_name && (
							<strong className="table-issue-position">{warning.position_name}</strong>
						)}
						{!warning.field && <p>{warning.message}</p>}
						{warning.value && (
							<div className="table-issue-value">
								<span>В ячейке</span>
								<b>{warning.value}</b>
							</div>
						)}
						{warning.fix && !warning.field && <p className="table-issue-help">{warning.fix}</p>}
						{warning.ai_tip && !suggestion && (
							<p className="table-issue-help">
								<b>Совет ИИ</b> · {warning.ai_tip}
							</p>
						)}
						{suggestion?.message && <p className="table-issue-help">{suggestion.message}</p>}
						{suggestion?.options.map(({ value, reason }) => (
							<div className="table-suggested-value" key={String(value)}>
								<span>{reason}</span>
								<Button
									size="small"
									icon={<Sparkles size={14} />}
									onClick={() => setValue(warning.id, value)}
								>
									Подставить {typeof value === 'number' ? nf.format(value) : unit(value)}
								</Button>
							</div>
						))}
						{singularCell && warning.sheet && (
							<div className="table-cell-fix">
								<div>
									{warning.field === 'Единица измерения' ? (
										<Select
											allowClear
											placeholder="Ед. изм."
											value={values[warning.id] || undefined}
											onChange={(value) => setValue(warning.id, value)}
											options={[
												...new Set([
													'м',
													'шт',
													'м²',
													'м³',
													'кг',
													'компл',
													'сист',
													'л',
													'т',
													...(suggestion?.options.map(({ value }) => String(value)) || []),
												]),
											].map((value) => ({
												value,
												label: unit(value),
											}))}
										/>
									) : (
										<InputNumber
											min={0}
											placeholder="Новое значение"
											value={
												typeof values[warning.id] === 'number'
													? (values[warning.id] as number)
													: null
											}
											onChange={(value) => setValue(warning.id, value)}
										/>
									)}
									<Button
										type="primary"
										loading={busy}
										disabled={values[warning.id] === undefined || values[warning.id] === null}
										onClick={() => fixCell(warning, values[warning.id])}
									>
										Исправить
									</Button>
								</div>
							</div>
						)}
						{warning.duplicates?.map((group) => {
							const key = warning.id + group.date;
							const strategy = strategies[key] || 'sum';
							return (
								<div className="duplicate-fix" key={group.date}>
									<label>
										{dayjs(group.date).format('D MMMM YYYY')} · {group.cells.join(', ')}
									</label>
									<Select
										value={strategy}
										onChange={(value) => setStrategies((current) => ({ ...current, [key]: value }))}
										options={[
											{ value: 'sum', label: 'Объединить объёмы, убрать повтор даты' },
											{ value: 'keep_first', label: 'Оставить первый столбец, очистить дубликаты' },
											{ value: 'rename', label: 'Назначить последнему столбцу другую дату' },
										]}
									/>
									{strategy === 'rename' && (
										<DatePicker
											value={dayjs(replacementDates[key] || group.date)}
											onChange={(value) =>
												value &&
												setReplacementDates((current) => ({
													...current,
													[key]: value.format('YYYY-MM-DD'),
												}))
											}
										/>
									)}
									<Button
										loading={busy}
										onClick={() =>
											void applyImportChanges({
												duplicates: [
													{
														sheet: warning.sheet!,
														date: group.date,
														strategy,
														...(strategy === 'rename'
															? { new_date: replacementDates[key] || group.date }
															: {}),
													},
												],
											})
										}
									>
										Применить исправление
									</Button>
								</div>
							);
						})}
						<Button
							size="small"
							type={ack.includes(warning.id) ? 'primary' : 'default'}
							icon={ack.includes(warning.id) ? <Check size={13} /> : undefined}
							onClick={() =>
								setAck((current) =>
									current.includes(warning.id)
										? current.filter((id) => id !== warning.id)
										: [...current, warning.id],
								)
							}
						>
							{ack.includes(warning.id)
								? 'Подтверждено'
								: warning.confirmation_label || 'Проверено, подтверждаю'}
						</Button>
					</section>
				);
			})}
			{suggestionError && (
				<Alert
					type="warning"
					showIcon
					message={suggestionError}
					action={
						<Button size="small" onClick={() => setSuggestionAttempt(suggestionAttempt + 1)}>
							Повторить подбор
						</Button>
					}
				/>
			)}
			{preview.warnings
				.filter((warning) => warning.severity === 'info')
				.map((warning) => (
					<Alert key={warning.id} type="info" showIcon message={warning.message} />
				))}
		</div>
	);
	const positionCards = (
		<div className="import-position-list">
			<Input
				aria-label="Поиск в импортируемой таблице"
				value={query}
				allowClear
				onChange={(event) => setQuery(event.target.value)}
				prefix={<Search size={16} />}
				placeholder="Найти работу или строку…"
			/>
			{positions.map((position) => (
				<section className="import-position-card" key={position.id}>
					<div className="import-position-title">
						<span>{position.source_row}</span>
						<b>{position.name}</b>
						<Button
							type="text"
							size="small"
							aria-label={'Изменить строку ' + position.source_row}
							icon={<Settings2 size={16} />}
							onClick={() => setEditing(editing === position.id ? null : position.id)}
						/>
					</div>
					<div className="import-position-values">
						<span>
							План{' '}
							<b>
								{nf.format(position.planned)} {unit(position.unit)}
							</b>
						</span>
						<span>
							Расценка{' '}
							<b>
								<Money value={position.rate} />
							</b>
						</span>
						<span>
							Лист <b>{position.source_sheet}</b>
						</span>
					</div>
					{editing === position.id && (
						<div className="position-inline-editor">
							<label>
								План
								<InputNumber
									min={0}
									value={
										values[position.id + ':planned'] === undefined
											? position.planned
											: (values[position.id + ':planned'] as number)
									}
									onChange={(value) => setValue(position.id + ':planned', value)}
								/>
							</label>
							<label>
								Расценка
								<InputNumber
									min={0}
									value={
										values[position.id + ':rate'] === undefined
											? position.rate
											: (values[position.id + ':rate'] as number)
									}
									onChange={(value) => setValue(position.id + ':rate', value)}
								/>
							</label>
							<label>
								Единица
								<Input
									value={String(values[position.id + ':unit'] ?? position.unit)}
									onChange={(event) => setValue(position.id + ':unit', event.target.value)}
								/>
							</label>
							<Button type="primary" loading={busy} onClick={() => savePosition(position)}>
								Сохранить ячейки
							</Button>
						</div>
					)}
				</section>
			))}
		</div>
	);
	const columns = (
		<div className="import-mapping-list">
			{mapping.map((sheet, index) => (
				<section className="import-mapping-card" key={sheet.name}>
					<h3>{sheet.name}</h3>
					<label>
						Строка заголовков
						<InputNumber
							min={1}
							value={sheet.header_row}
							onChange={(value) =>
								setMapping((current) =>
									current.map((item, otherIndex) =>
										otherIndex === index ? { ...item, header_row: value || 1 } : item,
									),
								)
							}
						/>
					</label>
					<label>
						Строка дат
						<InputNumber
							min={1}
							value={sheet.date_row}
							onChange={(value) =>
								setMapping((current) =>
									current.map((item, otherIndex) =>
										otherIndex === index ? { ...item, date_row: value || 1 } : item,
									),
								)
							}
						/>
					</label>
					{Object.entries({
						name: 'Название работы',
						unit: 'Единица измерения',
						planned: 'Плановый объём',
						rate: 'Расценка',
						completed: 'Выполнено ранее',
						section: 'Раздел',
					}).map(([field, label]) => (
						<label key={field}>
							{label}
							<Select
								allowClear
								value={sheet.mapping[field] || undefined}
								placeholder="Не указан"
								onChange={(column) =>
									setMapping((current) =>
										current.map((item, otherIndex) =>
											otherIndex === index
												? { ...item, mapping: { ...item.mapping, [field]: column || null } }
												: item,
										),
									)
								}
								options={sheet.columns.map((column) => ({
									value: column.index,
									label: column.label,
								}))}
							/>
						</label>
					))}
				</section>
			))}
			<Button block loading={busy} onClick={reviewImport}>
				Перепроверить структуру
			</Button>
		</div>
	);
	return (
		<Modal
			className="table-import-modal"
			title="Таблица объекта"
			width={780}
			open
			onCancel={() => setPreview(null)}
			footer={
				<div className="table-import-footer">
					<span>
						{preview.positions.length} работ · {preview.sheets.length} листов
					</span>
					<Button
						type="primary"
						loading={busy}
						disabled={
							resolving ||
							reconciliationPending ||
							problems.some((warning) => !ack.includes(warning.id))
						}
						onClick={() =>
							void commitImport({
								position_matches: positionMatches,
								reconciliation_acknowledged: reconciliationAccepted,
								reconciliation_version: reconciliation?.version || '',
								day_resolutions: dayResolutions,
							})
						}
					>
						{reconciliation?.needs_confirmation ? 'Применить изменения' : 'Подтвердить таблицу'}
					</Button>
				</div>
			}
		>
			<div className="import-file-heading">
				<span>
					<FileSpreadsheet size={22} />
				</span>
				<div>
					<b>{preview.name}</b>
					<small>{preview.source === 'bitrix' ? 'Связана с Битрикс24' : 'Загруженный файл'}</small>
				</div>
				{preview.source === 'bitrix' && !data?.config.has_webhook && (
					<Button
						size="small"
						onClick={() => {
							setPreview(null);
							openObjectSection('table');
						}}
					>
						Включить запись
					</Button>
				)}
			</div>
			<Tabs
				activeKey={tab}
				onChange={setTab}
				items={[
					...(reconciliation?.needs_confirmation
						? [
								{
									key: 'reconciliation',
									label: 'Изменения сметы',
									children: (
										<CatalogueReconciliation
											plan={reconciliation}
											dayResolutions={dayResolutions}
											onResolveDays={(value) => {
												setDayResolutions(
													Object.fromEntries(
														reconciliation.report_conflicts.map((report) => [report.date, value]),
													),
												);
												setReconciliationAccepted(false);
											}}
											positions={preview.positions}
											selected={positionMatches}
											onSelect={(id, value) => {
												setPositionMatches((current) => ({ ...current, [id]: value }));
												setReconciliationAccepted(false);
											}}
											accepted={reconciliationAccepted}
											onAccept={setReconciliationAccepted}
											busy={resolving}
											onResolve={() => void resolveReconciliation()}
										/>
									),
								},
							]
						: []),
					{
						key: 'issues',
						label: <>Проверка {problems.length > 0 && <Tag color="gold">{problems.length}</Tag>}</>,
						children: issueCards,
					},
					{
						key: 'positions',
						label: `Все работы (${preview.positions.length})`,
						children: positionCards,
					},
					{ key: 'columns', label: 'Столбцы', children: columns },
				]}
			/>
		</Modal>
	);
}
