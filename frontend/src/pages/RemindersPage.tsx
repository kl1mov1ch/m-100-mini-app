import { App, Button, Input, Segmented, Select, Switch, TimePicker } from 'antd';
import { Send } from 'lucide-react';
import { useEffect, useState } from 'react';
import dayjs from '../lib/date';
import { request } from '../lib/api';
import type { WorkspaceView } from '../App';
import { CompactWorkEditor } from '../components/CompactRow';
import './reminders.css';

type Audience = 'missing' | 'selected' | 'all';
type ReminderConfig = {
	enabled: boolean;
	weekdays: number[];
	time: string;
	text: string;
	audience: Audience;
	recipient_ids: string[];
};
type ReminderData = {
	settings: ReminderConfig;
	users: { telegram_id: string; name: string; role: string }[];
	recipients: { telegram_id: string }[];
	deliveries: { name: string; status: string; error: string; created_at: string }[];
};
type DeliveryResult = { sent: number; failed: number; skipped: number };

const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const audiences = [
	{ value: 'missing', label: 'Без отчёта' },
	{ value: 'selected', label: 'Выбранные' },
	{ value: 'all', label: 'Всем' },
] satisfies { value: Audience; label: string }[];

function deliveryStatus(status: string) {
	if (status === 'sent') return 'Отправлено';
	if (status === 'sending') return 'Отправляется';
	return 'Не доставлено';
}

export function RemindersPage({ workspace }: { workspace: WorkspaceView }) {
	const { message, modal } = App.useApp();
	const [data, setData] = useState<ReminderData>();
	const [config, setConfig] = useState<ReminderConfig>();
	const [busy, setBusy] = useState(false);
	const load = async () => {
		const result = await request<ReminderData>('/admin/reminders');
		setData(result);
		setConfig(result.settings);
	};
	useEffect(() => {
		if (workspace.isAdmin) void load().catch((error) => message.error(error.message));
	}, [workspace.isAdmin]);
	if (!workspace.isAdmin) return null;
	if (!config || !data) return <div role="status">Загружаем уведомления…</div>;

	const update = (patch: Partial<ReminderConfig>) => setConfig({ ...config, ...patch });
	const selected = new Set(config.recipient_ids);
	const recipientCount =
		config.audience === 'missing'
			? data.recipients.length
			: config.audience === 'all'
				? data.users.length
				: data.users.filter((user) => selected.has(user.telegram_id)).length;
	const valid = !!config.text.trim() && (config.audience !== 'selected' || recipientCount > 0);
	const save = async () => {
		setBusy(true);
		try {
			await request('/admin/reminders/settings', config);
			message.success('Расписание сохранено');
			await load();
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const sendTest = async () => {
		setBusy(true);
		try {
			const result = await request<DeliveryResult>('/admin/reminders/test', {
				request_id: crypto.randomUUID(),
				text: config.text.trim(),
			});
			if (result.sent) message.success('Сообщение отправлено вам в Telegram');
			else message.warning('Telegram не доставил сообщение. Проверьте разрешение для бота.');
			setData(await request<ReminderData>('/admin/reminders'));
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const send = () => {
		const requestId = crypto.randomUUID();
		modal.confirm({
			closable: true,
			title: 'Отправить в Telegram?',
			content: (
				<div className="notification-preview">
					<small>Получателей · {recipientCount}</small>
					<p>{config.text.trim()}</p>
					{config.audience === 'missing' && <small>Бот добавит список объектов без отчёта.</small>}
				</div>
			),
			okText: 'Отправить',
			cancelText: 'Отмена',
			onOk: async () => {
				const result = await request<DeliveryResult>('/admin/reminders/send', {
					request_id: requestId,
					audience: config.audience,
					recipient_ids: config.recipient_ids,
					text: config.text.trim(),
				});
				message.info(`Отправлено · ${result.sent}. Не доставлено · ${result.failed}.`);
				setData(await request<ReminderData>('/admin/reminders'));
			},
		});
	};
	return (
		<div className="notifications-page">
			<div className="page-title">
				<h1>Уведомления</h1>
			</div>
			<section className="settings-card notifications-card">
				<h2>Рассылка в Telegram</h2>
				<div className="notification-field">
					<span>Получатели</span>
					<Segmented
						aria-label="Получатели уведомления"
						block
						options={audiences}
						value={config.audience}
						onChange={(audience) => update({ audience })}
					/>
					{config.audience === 'selected' && (
						<Select
							aria-label="Выбрать пользователей Telegram"
							placeholder="Найти пользователя"
							mode="multiple"
							maxTagCount="responsive"
							optionFilterProp="label"
							value={config.recipient_ids}
							onChange={(recipient_ids) => update({ recipient_ids })}
							options={data.users.map(({ telegram_id, name, role }) => ({
								value: telegram_id,
								label: `${name} · ${role === 'admin' ? 'Администратор' : 'Мастер'}`,
							}))}
						/>
					)}
					<small>Получателей сейчас · {recipientCount}</small>
				</div>
				<label className="notification-field">
					<span>Текст сообщения</span>
					<Input.TextArea
						value={config.text}
						maxLength={1500}
						autoSize={{ minRows: 3, maxRows: 8 }}
						onChange={(event) => update({ text: event.target.value })}
					/>
				</label>
				<div className="notification-actions">
					<Button
						icon={<Send size={16} />}
						onClick={send}
						disabled={!valid || !recipientCount || busy}
					>
						Отправить сейчас
					</Button>
					<Button type="text" disabled={!config.text.trim() || busy} onClick={sendTest}>
						Проверить на себе
					</Button>
				</div>
			</section>
			<section className="settings-card notifications-card">
				<div className="notification-section-title">
					<div>
						<h2>Расписание</h2>
						<small>Время Минска</small>
					</div>
					<Switch
						aria-label="Отправлять по расписанию"
						checked={config.enabled}
						onChange={(enabled) => update({ enabled })}
					/>
				</div>
				<div className="notification-field">
					<span>Дни отправки</span>
					<div className="notification-days" role="group" aria-label="Дни отправки">
						{weekdays.map((label, day) => (
							<button
								key={label}
								type="button"
								aria-pressed={config.weekdays.includes(day)}
								onClick={() =>
									update({
										weekdays: config.weekdays.includes(day)
											? config.weekdays.filter((value) => value !== day)
											: [...config.weekdays, day].sort(),
									})
								}
							>
								{label}
							</button>
						))}
					</div>
				</div>
				<label className="notification-field">
					<span>Время отправки</span>
					<TimePicker
						aria-label="Время отправки"
						format="HH:mm"
						allowClear={false}
						value={dayjs('2026-01-01T' + config.time)}
						onChange={(value) => value && update({ time: value.format('HH:mm') })}
						inputReadOnly
					/>
				</label>
				<Button
					type="primary"
					loading={busy}
					disabled={!valid || !config.weekdays.length}
					onClick={save}
				>
					Сохранить расписание
				</Button>
			</section>
			<section className="settings-card notifications-card">
				<h2>Последние отправки</h2>
				{data.deliveries.length ? (
					<div className="compact-list">
						{data.deliveries.map((item, index) => (
							<CompactWorkEditor
								key={item.created_at + index}
								title={item.name || 'Пользователь Telegram'}
								description={dayjs(item.created_at).format('D MMMM, HH:mm')}
								meta={deliveryStatus(item.status)}
								attention={item.status === 'failed'}
							>
								<p>{deliveryStatus(item.status)}</p>
								{item.error && <p className="form-error">{item.error}</p>}
							</CompactWorkEditor>
						))}
					</div>
				) : (
					<small>Отправок пока нет.</small>
				)}
			</section>
		</div>
	);
}
