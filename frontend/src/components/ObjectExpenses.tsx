import { Alert, App, Button, Empty, Form, Input, InputNumber, Modal, Spin } from 'antd';
import { ChevronRight, Plus, ReceiptText } from 'lucide-react';
import { useEffect, useState } from 'react';
import { request } from '../lib/api';
import { Money } from '../lib/format';

type ExpenseValues = {
	date: string;
	name: string;
	unit: string;
	quantity: string;
	rate: string;
	note: string;
};
type Expense = ExpenseValues & { id: string; revision: number; amount: string };
type ExpenseState = {
	rows: Expense[];
	templates: { id: string; name: string; unit: string; rate: number }[];
	total: string;
	can_edit: boolean;
	can_sync: boolean;
	sync_status: 'local' | 'pending' | 'synced';
};

export function ObjectExpenses({ project, day }: { project: string; day: string }) {
	const { message } = App.useApp();
	const [form] = Form.useForm<ExpenseValues>();
	const [list, setList] = useState<ExpenseState>();
	const [error, setError] = useState('');
	const [open, setOpen] = useState(false);
	const [editing, setEditing] = useState<Expense>();
	const [busy, setBusy] = useState(false);
	useEffect(() => {
		const controller = new AbortController();
		void request<ExpenseState>('/object/expenses', undefined, project, controller.signal)
			.then(setList)
			.catch((failure: Error) => {
				if (!controller.signal.aborted) setError(failure.message);
			});
		return () => controller.abort();
	}, [project]);

	const openEditor = (row?: Expense, template?: ExpenseState['templates'][number]) => {
		setEditing(row);
		setOpen(true);
		form.setFieldsValue(
			row || {
				date: day,
				name: template?.name || '',
				unit: template?.unit || 'шт.',
				quantity: '1',
				rate: template ? String(template.rate) : undefined,
				note: '',
			},
		);
	};
	const save = async (values: ExpenseValues) => {
		setBusy(true);
		try {
			const next = await request<ExpenseState>(
				'/object/expenses',
				{ ...values, id: editing?.id, revision: editing?.revision },
				project,
			);
			setList(next);
			setOpen(false);
			message.success('Расход сохранён');
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const sync = async () => {
		setBusy(true);
		try {
			setList(await request<ExpenseState>('/object/expenses/sync', {}, project));
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const required = [{ required: true, message: 'Заполните поле' }];
	if (!list)
		return (
			<section className="object-panel">
				{error ? <Alert type="error" message={error} /> : <Spin />}
			</section>
		);

	return (
		<section className="object-panel object-expenses">
			<div className="object-expense-heading">
				<div>
					<h2>Доп. расходы</h2>
					<strong>
						<Money value={Number(list.total)} />
					</strong>
				</div>
				{list.can_edit && (
					<Button type="primary" icon={<Plus size={17} />} onClick={() => openEditor()}>
						Добавить
					</Button>
				)}
			</div>
			{list.rows.length > 0 && list.sync_status !== 'synced' && (
				<Alert
					type={list.sync_status === 'pending' ? 'warning' : 'info'}
					message={
						list.sync_status === 'pending'
							? 'Ожидает записи в Битрикс24'
							: 'Расходы сохранены в приложении'
					}
					action={
						list.can_edit &&
						list.can_sync && (
							<Button size="small" loading={busy} onClick={() => void sync()}>
								{list.sync_status === 'pending' ? 'Повторить' : 'Записать'}
							</Button>
						)
					}
				/>
			)}
			{list.rows.length ? (
				<div className="compact-list object-expense-list">
					{list.rows.map((row) => (
						<button
							type="button"
							key={row.id}
							disabled={!list.can_edit}
							onClick={() => openEditor(row)}
						>
							<ReceiptText size={18} />
							<span>
								<strong>{row.name}</strong>
								<small>
									{row.date.split('-').reverse().join('.')} · {row.quantity} {row.unit}
								</small>
							</span>
							<Money value={Number(row.amount)} />
							{list.can_edit && <ChevronRight size={15} />}
						</button>
					))}
				</div>
			) : (
				<Empty
					image={Empty.PRESENTED_IMAGE_SIMPLE}
					description="Дополнительных расходов пока нет"
				/>
			)}
			{list.can_edit && list.templates.length > 0 && (
				<details className="object-expense-templates">
					<summary>Позиции из исходной сметы</summary>
					{list.templates.map((template) => (
						<Button
							key={template.id}
							type="text"
							icon={<Plus size={16} />}
							onClick={() => openEditor(undefined, template)}
						>
							{template.name}
						</Button>
					))}
				</details>
			)}
			<Modal
				open={open}
				forceRender
				title={editing ? 'Изменить расход' : 'Добавить расход'}
				okText="Сохранить"
				cancelText="Отмена"
				confirmLoading={busy}
				onCancel={() => !busy && setOpen(false)}
				onOk={form.submit}
			>
				<Form form={form} layout="vertical" onFinish={(values) => void save(values)}>
					<Form.Item name="name" label="Работа или расход" rules={required}>
						<Input placeholder="Например, топливо" maxLength={300} />
					</Form.Item>
					<Form.Item name="date" label="Дата" rules={required}>
						<Input type="date" />
					</Form.Item>
					<div className="object-expense-fields">
						<Form.Item name="quantity" label="Количество" rules={required}>
							<InputNumber stringMode min="0.0001" max="1000000" precision={4} controls={false} />
						</Form.Item>
						<Form.Item name="unit" label="Ед. изм." rules={required}>
							<Input maxLength={24} />
						</Form.Item>
					</div>
					<Form.Item name="rate" label="Цена за единицу, BYN" rules={required}>
						<InputNumber stringMode min="0" max="1000000" precision={4} controls={false} />
					</Form.Item>
					<Form.Item name="note" label="Примечание">
						<Input.TextArea maxLength={500} autoSize />
					</Form.Item>
				</Form>
			</Modal>
		</section>
	);
}
