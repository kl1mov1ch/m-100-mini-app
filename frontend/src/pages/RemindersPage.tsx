import { App, Button, Input, Segmented, Select } from 'antd';
import { ChevronDown, Send } from 'lucide-react';
import { type ClipboardEvent, useEffect, useState } from 'react';
import dayjs from '../lib/date';
import { request } from '../lib/api';
import type { WorkspaceView } from '../App';
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
type Delivery = {
	telegram_id: string;
	run_key: string;
	day: string;
	name: string;
	status: string;
	error: string;
	created_at: string;
};
type ReminderData = {
	settings: ReminderConfig;
	users: { telegram_id: string; name: string; role: string }[];
	recipients: { telegram_id: string }[];
	deliveries: Delivery[];
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

function scheduleTime(hours: string, minutes: string) {
	if (![hours, minutes].every((value) => /^\d{1,2}$/.test(value))) return null;
	if (Number(hours) > 23 || Number(minutes) > 59) return null;
	return hours.padStart(2, '0') + ':' + minutes.padStart(2, '0');
}

function DeliveryHistory({ deliveries }: { deliveries: Delivery[] }) {
	const groups = new Map<string, Delivery[]>();
	for (const item of deliveries) {
		const day = dayjs(item.created_at).format('YYYY-MM-DD');
		const group = groups.get(day);
		if (group) group.push(item);
		else groups.set(day, [item]);
	}
	const dates = [...groups.keys()].sort().reverse();
	return (
		<section className="settings-card notifications-card">
			<h2>Последние отправки</h2>
			{dates.length === 0 && <small>Отправок пока нет.</small>}
			{dates.map((day, index) => {
				const rows = groups.get(day)!;
				const sent = rows.filter((item) => item.status === 'sent').length;
				const failed = rows.filter((item) => item.status === 'failed').length;
				const pending = rows.length - sent - failed;
				return (
					<details className="notification-history-day" key={day} open={index === 0}>
						<summary>
							<span>
								<strong>
									<time dateTime={day}>{dayjs(day).format('D MMMM YYYY')}</time>
								</strong>
								<small>
									{[
										sent > 0 && `Доставлено · ${sent}`,
										failed > 0 && `Не доставлено · ${failed}`,
										pending > 0 && `В процессе · ${pending}`,
									]
										.filter(Boolean)
										.join('  ·  ')}
								</small>
							</span>
							<ChevronDown size={17} aria-hidden />
						</summary>
						<ul>
							{rows.map((item) => (
								<li key={item.day + ':' + item.run_key + ':' + item.telegram_id}>
									<time dateTime={item.created_at}>{dayjs(item.created_at).format('HH:mm')}</time>
									<span>{item.name || 'Пользователь Telegram'}</span>
									<small
										className={
											item.status === 'failed' ? 'notification-delivery-failed' : undefined
										}
									>
										{deliveryStatus(item.status)}
									</small>
									{item.error && (
										<small className="notification-delivery-error">{item.error}</small>
									)}
								</li>
							))}
						</ul>
					</details>
				);
			})}
		</section>
	);
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
	const [hours = '', minutes = ''] = config.time.split(':');
	const time = scheduleTime(hours, minutes);
	const updateTime = (part: 'hours' | 'minutes', value: string) => {
		const digits = value.replace(/\D/g, '').slice(0, 2);
		update({ time: part === 'hours' ? digits + ':' + minutes : hours + ':' + digits });
	};
	const pasteTime = (event: ClipboardEvent<HTMLInputElement>) => {
		const match = /^(\d{1,2}):(\d{1,2})$/.exec(event.clipboardData.getData('text').trim());
		if (!match) return;
		event.preventDefault();
		const pasted = scheduleTime(match[1], match[2]);
		if (pasted) update({ time: pasted });
		else message.warning('Укажите время от 00:00 до 23:59');
	};
	const selected = new Set(config.recipient_ids);
	const recipientCount =
		config.audience === 'missing'
			? data.recipients.length
			: config.audience === 'all'
				? data.users.length
				: data.users.filter((user) => selected.has(user.telegram_id)).length;
	const valid = !!config.text.trim() && (config.audience !== 'selected' || recipientCount > 0);
	const save = async () => {
		if (!time) return;
		setBusy(true);
		try {
			await request('/admin/reminders/settings', { ...config, time });
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
				<h2>Расписание</h2>
				<label className="notification-schedule-switch">
					<span>
						<strong>Автоматическая отправка</strong>
						<small>{config.enabled ? 'Включена' : 'Выключена'}</small>
					</span>
					<input
						type="checkbox"
						role="switch"
						aria-label="Автоматическая отправка"
						checked={config.enabled}
						onChange={(event) => update({ enabled: event.target.checked })}
					/>
					<span className="notification-switch-track" aria-hidden />
				</label>
				<div className="notification-schedule-fields">
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
					<fieldset className="notification-field notification-time">
						<legend>Время по Минску</legend>
						<div>
							<Input
								aria-label="Часы"
								inputMode="numeric"
								value={hours}
								placeholder="ЧЧ"
								onFocus={(event) => event.target.select()}
								onPaste={pasteTime}
								status={time ? undefined : 'error'}
								onChange={(event) => updateTime('hours', event.target.value)}
							/>
							<span aria-hidden>:</span>
							<Input
								aria-label="Минуты"
								inputMode="numeric"
								value={minutes}
								placeholder="ММ"
								onFocus={(event) => event.target.select()}
								onPaste={pasteTime}
								status={time ? undefined : 'error'}
								onChange={(event) => updateTime('minutes', event.target.value)}
							/>
						</div>
						{!time && (
							<small className="notification-delivery-failed">
								Укажите время от 00:00 до 23:59
							</small>
						)}
					</fieldset>
				</div>
				<Button
					type="primary"
					loading={busy}
					disabled={!valid || !config.weekdays.length || !time}
					onClick={save}
				>
					Сохранить расписание
				</Button>
			</section>
			<DeliveryHistory deliveries={data.deliveries} />
		</div>
	);
}
