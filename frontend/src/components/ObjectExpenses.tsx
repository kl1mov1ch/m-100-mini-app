import { Alert, App, Button, Form, Input, InputNumber, Modal, Skeleton } from 'antd';
import type { Dayjs } from 'dayjs';
import { ChevronRight, Mic, Plus, ReceiptText, Sparkles, Square, X } from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useAudioInput } from '../hooks/useAudioInput';
import { request } from '../lib/api';
import dayjs from '../lib/date';
import { countLabel, Currency, Money } from '../lib/format';
import { DatePicker } from './ResponsiveDatePicker';

type ExpenseValues = {
	date: string;
	name: string;
	unit: string;
	quantity: string;
	rate: string;
	note: string;
};
type Expense = ExpenseValues & { id: string; revision: number; amount: string };
type Draft = Partial<ExpenseValues> & { quote?: string; key: string };
type Editor = { values: Partial<ExpenseValues>; saved?: Expense; draft?: Draft };
type ExpenseState = {
	rows: Expense[];
	templates: { id: string; name: string; unit: string; rate: number }[];
	total: string;
	can_edit: boolean;
	can_sync: boolean;
	sync_status: 'local' | 'pending' | 'synced';
};

const endpoint = '/object/expenses';
const required = [{ required: true, message: 'Заполните поле' }];
const decimalRules = [
	...required,
	{ pattern: /^\d+(?:\.\d{1,4})?$/, message: 'До четырёх знаков после запятой' },
];
const ready = (row: Partial<ExpenseValues>) =>
	!!(
		row.name?.trim() &&
		row.unit?.trim() &&
		Number(row.quantity) > 0 &&
		row.rate &&
		Number(row.rate) >= 0
	);
const volume = new Intl.NumberFormat('ru-BY', { maximumFractionDigits: 4 });
function amount(quantity: string | undefined, rate: string | undefined) {
	const scaled = (value: string | undefined) => BigInt(Math.round(Number(value || 0) * 10000));
	return Number((scaled(quantity) * scaled(rate) + 500000n) / 1000000n) / 100;
}

function ExpenseRow({
	name,
	detail,
	amount,
	onOpen,
}: {
	name: string;
	detail: ReactNode;
	amount?: number;
	onOpen?: () => void;
}) {
	const content = (
		<>
			<span className="compact-row-main">
				<strong title={name}>{name}</strong>
				<span
					className="compact-row-description"
					title={typeof detail === 'string' ? detail : undefined}
				>
					{detail}
				</span>
			</span>
			{amount !== undefined && (
				<span className="compact-row-aside">
					<strong>
						<Money value={amount} />
					</strong>
				</span>
			)}
			{onOpen && <ChevronRight className="compact-row-arrow" size={17} aria-hidden />}
		</>
	);
	return onOpen ? (
		<button className="compact-row expense-row" type="button" onClick={onOpen}>
			{content}
		</button>
	) : (
		<div className="compact-row expense-row">{content}</div>
	);
}

export function ObjectExpenses({ project, day }: { project: string; day: string }) {
	const { message } = App.useApp();
	const [form] = Form.useForm<ExpenseValues>();
	const [list, setList] = useState<ExpenseState>();
	const [error, setError] = useState('');
	const [editor, setEditor] = useState<Editor>();
	const [pickingDate, setPickingDate] = useState(false);
	const [busy, setBusy] = useState(false);
	const [text, setText] = useState('');
	const [drafts, setDrafts] = useState<Draft[]>([]);
	const [parsing, setParsing] = useState(false);
	const [parseError, setParseError] = useState('');
	const [loadVersion, reload] = useState(0);
	const parseRequest = useRef<AbortController>(null);
	const audio = useAudioInput(project, 'expenses', text, setText);
	const quantity = Form.useWatch('quantity', form);
	const rate = Form.useWatch('rate', form);

	useEffect(() => {
		const controller = new AbortController();
		setError('');
		void request<ExpenseState>(endpoint, undefined, project, controller.signal)
			.then(setList)
			.catch((failure: Error) => {
				if (!controller.signal.aborted) setError(failure.message);
			});
		return () => controller.abort();
	}, [project, loadVersion]);
	useEffect(() => () => parseRequest.current?.abort(), []);

	const openEditor = (next: Editor) => {
		form.resetFields();
		form.setFieldsValue(next.values);
		setEditor(next);
	};

	const parse = async () => {
		const controller = new AbortController();
		parseRequest.current = controller;
		setParsing(true);
		setParseError('');
		try {
			const result = await request<{ rows: Omit<Draft, 'key'>[] }>(
				endpoint + '/parse',
				{ text: text.trim() },
				project,
				controller.signal,
			);
			if (controller.signal.aborted) return;
			setDrafts((current) => [
				...current,
				...result.rows.map((row) => ({
					name: row.name,
					quantity: row.quantity ?? undefined,
					unit: row.unit ?? undefined,
					rate: row.rate ?? undefined,
					quote: row.quote,
					date: day,
					note: '',
					key: crypto.randomUUID(),
				})),
			]);
			setText('');
		} catch (failure) {
			if (!controller.signal.aborted) setParseError((failure as Error).message);
		} finally {
			if (!controller.signal.aborted) setParsing(false);
		}
	};

	const save = async (values: ExpenseValues) => {
		if (editor?.draft) {
			setDrafts((rows) =>
				rows.map((row) => (row.key === editor.draft?.key ? { ...row, ...values } : row)),
			);
			setEditor(undefined);
			return;
		}
		setBusy(true);
		try {
			setList(
				await request<ExpenseState>(
					endpoint,
					{ ...values, id: editor?.saved?.id, revision: editor?.saved?.revision },
					project,
				),
			);
			setEditor(undefined);
			message.success('Расход сохранён');
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setBusy(false);
		}
	};

	const saveDrafts = async () => {
		setBusy(true);
		try {
			setList(
				await request<ExpenseState>(
					endpoint + '/batch',
					{ rows: drafts.map(({ key, quote, ...values }) => ({ ...values, draft_id: key })) },
					project,
				),
			);
			setDrafts([]);
			message.success('Расходы сохранены');
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const sync = async () => {
		setBusy(true);
		try {
			setList(await request<ExpenseState>(endpoint + '/sync', {}, project));
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setBusy(false);
		}
	};

	if (!list)
		return (
			<section className="object-panel">
				{error ? (
					<Alert
						type="error"
						message={error}
						action={
							<Button size="small" onClick={() => reload((v) => v + 1)}>
								Повторить
							</Button>
						}
					/>
				) : (
					<Skeleton active title={{ width: '40%' }} paragraph={{ rows: 2 }} />
				)}
			</section>
		);

	const reviewCount = drafts.filter((row) => !ready(row)).length;
	const blocked = busy || parsing || audio.recording || audio.pending;
	const transcriptStatus = audio.recording
		? audio.live
			? 'Говорите, текст появится в поле'
			: 'Идёт запись…'
		: audio.activity === 'transcribing'
			? 'Переводим запись в текст…'
			: '';
	return (
		<section className="object-expenses">
			<div className="object-panel expense-summary">
				<span className="expense-summary-icon">
					<ReceiptText size={20} aria-hidden />
				</span>
				<div>
					<h2>Доп. расходы</h2>
					<small>{countLabel(list.rows.length, 'запись', 'записи', 'записей')}</small>
				</div>
				<strong>
					<Money value={Number(list.total)} />
				</strong>
			</div>

			{list.can_edit && drafts.length === 0 && (
				<section className="object-panel expense-composer" aria-label="Добавление расходов">
					<div className="expense-heading">
						<h3>Добавить расходы</h3>
						<Button
							type="text"
							icon={<Plus size={16} />}
							disabled={blocked}
							onClick={() => openEditor({ values: { date: day, quantity: '1', unit: 'шт.' } })}
						>
							Вручную
						</Button>
					</div>
					<Input.TextArea
						aria-label="Описание дополнительных расходов"
						placeholder="Например, топливо 20 л по 2,50; аренда крана 3 часа по 180"
						value={text}
						onChange={(event) => {
							setText(event.target.value);
							setParseError('');
						}}
						autoSize={{ minRows: 2, maxRows: 5 }}
						maxLength={8000}
						readOnly={blocked}
					/>
					<div className="expense-compose-actions">
						<Button
							aria-label={audio.recording ? 'Остановить запись' : 'Надиктовать расходы'}
							icon={audio.recording ? <Square size={17} /> : <Mic size={19} />}
							danger={audio.recording}
							loading={audio.pending}
							disabled={busy || parsing}
							onClick={audio.toggleRecording}
						/>
						<Button
							type="primary"
							icon={<Sparkles size={16} />}
							loading={parsing}
							disabled={blocked || !text.trim()}
							onClick={() => void parse()}
						>
							Разобрать расходы
						</Button>
					</div>
					{transcriptStatus && <small role="status">{transcriptStatus}</small>}
					{parseError && <Alert type="error" message={parseError} />}
				</section>
			)}

			{drafts.length > 0 && (
				<section className="object-panel expense-review" aria-label="Черновики расходов">
					<div className="expense-heading">
						<h3>К проверке</h3>
						<small>{countLabel(drafts.length, 'позиция', 'позиции', 'позиций')}</small>
					</div>
					<div className="compact-list">
						{drafts.map((row) => (
							<div
								className="expense-draft"
								key={row.key}
								data-incomplete={!ready(row) || undefined}
							>
								<ExpenseRow
									name={row.name || 'Доп. работа'}
									detail={
										ready(row) ? (
											<>
												{volume.format(Number(row.quantity))} {row.unit} ·{' '}
												<span className="money">
													{volume.format(Number(row.rate))}
													<Currency />
												</span>{' '}
												за ед.
											</>
										) : (
											'Уточните количество, единицу или цену'
										)
									}
									amount={ready(row) ? amount(row.quantity, row.rate) : undefined}
									onOpen={() => !busy && openEditor({ values: row, draft: row })}
								/>
								<Button
									type="text"
									aria-label={`Убрать черновик «${row.name}»`}
									disabled={busy}
									icon={<X size={18} />}
									onClick={() => setDrafts((rows) => rows.filter((item) => item.key !== row.key))}
								/>
							</div>
						))}
					</div>
					{reviewCount > 0 && (
						<small role="status">Откройте отмеченные позиции и заполните данные.</small>
					)}
					<Button
						type="primary"
						block
						disabled={reviewCount > 0}
						loading={busy}
						onClick={() => void saveDrafts()}
					>
						Сохранить расходы
					</Button>
				</section>
			)}

			{list.rows.length > 0 && list.sync_status !== 'synced' && (
				<div className="expense-sync">
					<small role="status">
						{list.sync_status === 'pending'
							? 'Ожидает записи в Битрикс24'
							: 'Сохранено в приложении'}
					</small>
					{list.can_edit && list.can_sync && (
						<Button size="small" loading={busy} onClick={() => void sync()}>
							{list.sync_status === 'pending' ? 'Повторить' : 'Записать'}
						</Button>
					)}
				</div>
			)}

			{list.rows.length > 0 && (
				<section className="expense-records" aria-label="Сохранённые расходы">
					<h3>Сохранённые расходы</h3>
					<div className="compact-list">
						{list.rows.map((row) => (
							<ExpenseRow
								key={row.id}
								name={row.name}
								detail={`${row.date.split('-').reverse().join('.')} · ${volume.format(Number(row.quantity))} ${row.unit}`}
								amount={Number(row.amount)}
								onOpen={list.can_edit ? () => openEditor({ values: row, saved: row }) : undefined}
							/>
						))}
					</div>
				</section>
			)}
			{list.can_edit && list.templates.length > 0 && (
				<details className="object-panel expense-templates">
					<summary>Позиции из исходной сметы</summary>
					<div className="compact-list">
						{list.templates.map((item) => (
							<ExpenseRow
								key={item.id}
								name={item.name}
								detail={
									<>
										<span className="money">
											{volume.format(item.rate)}
											<Currency />
										</span>{' '}
										/ {item.unit}
									</>
								}
								onOpen={() =>
									openEditor({
										values: {
											date: day,
											name: item.name,
											unit: item.unit,
											quantity: '1',
											rate: String(item.rate),
										},
									})
								}
							/>
						))}
					</div>
				</details>
			)}

			<Modal
				open={!!editor && !pickingDate}
				forceRender
				focusTriggerAfterClose={!pickingDate}
				className="expense-editor"
				title={
					editor?.draft ? 'Проверить расход' : editor?.saved ? 'Изменить расход' : 'Добавить расход'
				}
				okText={editor?.draft ? 'Применить' : 'Сохранить'}
				cancelText="Отмена"
				confirmLoading={busy}
				onCancel={() => !busy && setEditor(undefined)}
				onOk={form.submit}
			>
				{editor?.draft?.quote && <p className="expense-quote">{editor.draft.quote}</p>}
				<Form
					form={form}
					layout="vertical"
					requiredMark={false}
					onFinish={(values) => void save(values)}
				>
					<Form.Item name="name" label="Название" rules={[{ ...required[0], whitespace: true }]}>
						<Input maxLength={300} autoComplete="off" />
					</Form.Item>
					<div className="expense-fields">
						<Form.Item name="quantity" label="Количество" rules={decimalRules}>
							<InputNumber
								stringMode
								min="0.0001"
								max="1000000"
								decimalSeparator=","
								controls={false}
								inputMode="decimal"
							/>
						</Form.Item>
						<Form.Item name="unit" label="Ед. изм." rules={[{ ...required[0], whitespace: true }]}>
							<Input maxLength={24} autoComplete="off" />
						</Form.Item>
						<Form.Item name="rate" label="Цена за ед." rules={decimalRules}>
							<InputNumber
								stringMode
								min="0"
								max="1000000"
								decimalSeparator=","
								controls={false}
								inputMode="decimal"
								suffix={<Currency />}
							/>
						</Form.Item>
						<Form.Item
							name="date"
							label="Дата"
							rules={required}
							getValueProps={(value?: string) => ({ value: value ? dayjs(value) : null })}
							getValueFromEvent={(value: Dayjs | null) => value?.format('YYYY-MM-DD')}
						>
							<DatePicker
								value={null}
								onChange={() => {}}
								allowClear={false}
								aria-label="Дата расхода"
								onOpenChange={setPickingDate}
							/>
						</Form.Item>
					</div>
					<details
						className="expense-note"
						key={editor?.saved?.id ?? editor?.draft?.key ?? 'new'}
						open={!!editor?.values.note}
					>
						<summary>Примечание</summary>
						<Form.Item name="note">
							<Input.TextArea
								aria-label="Примечание"
								maxLength={500}
								autoSize={{ minRows: 1, maxRows: 3 }}
							/>
						</Form.Item>
					</details>
				</Form>
				{Number(quantity) > 0 && rate && (
					<div className="expense-editor-total">
						<span>Сумма</span>
						<strong>
							<Money value={amount(quantity, rate)} />
						</strong>
					</div>
				)}
			</Modal>
		</section>
	);
}
