import { Segmented } from '../components/Segmented';
import { sortSearchOptions } from '../lib/search';
import { App } from 'antd';
import { Select } from '../components/Select';
import { Input } from '../components/Input';
import { Button } from '../components/Button';
import { confirmSheet, SheetModal as Modal } from '../components/SheetModal';
import { Clock3, Send } from 'lucide-react';
import { ChevronDown } from '../components/kit-icons';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
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

const twoDigits = (value: number) => String(value).padStart(2, '0');

function TimeWheel({
	label,
	count,
	initial,
	current,
	ready,
	onChange,
}: {
	label: string;
	count: number;
	initial: number;
	current: number;
	ready: boolean;
	onChange: (value: number) => void;
}) {
	const wheel = useRef<HTMLDivElement>(null);
	const move = (value: number) => {
		const node = wheel.current;
		if (!node) return;
		const next = Math.max(0, Math.min(count - 1, value));
		node.scrollTop = next * (node.children[0] as HTMLElement).offsetHeight;
		onChange(next);
	};
	useLayoutEffect(() => {
		if (ready) move(initial);
	}, [initial, ready]);
	return (
		<div className="notification-wheel">
			<span>{label}</span>
			<div
				ref={wheel}
				className="notification-wheel-options"
				aria-hidden={!ready}
				role="spinbutton"
				aria-label={label}
				aria-valuemin={0}
				aria-valuemax={count - 1}
				aria-valuenow={current}
				tabIndex={ready ? 0 : -1}
				onScroll={(event) => {
					const node = event.currentTarget;
					const height = (node.children[0] as HTMLElement).offsetHeight;
					if (height)
						onChange(Math.max(0, Math.min(count - 1, Math.round(node.scrollTop / height))));
				}}
				onKeyDown={(event) => {
					const values: Record<string, number> = {
						ArrowUp: current - 1,
						ArrowDown: current + 1,
						Home: 0,
						End: count - 1,
					};
					if (!Object.hasOwn(values, event.key)) return;
					event.preventDefault();
					move(values[event.key]);
				}}
			>
				{Array.from({ length: count }, (_, value) => (
					<button
						type="button"
						tabIndex={-1}
						key={value}
						data-current={current === value}
						onClick={() => move(value)}
					>
						{twoDigits(value)}
					</button>
				))}
			</div>
		</div>
	);
}

function ScheduleTime({ value, onChange }: { value: string; onChange: (time: string) => void }) {
	const [open, setOpen] = useState(false);
	const [ready, setReady] = useState(false);
	const [hours, minutes] = value.split(':').map(Number);
	const [hour, setHour] = useState(hours);
	const [minute, setMinute] = useState(minutes);
	return (
		<>
			<button
				className="notification-time-trigger"
				type="button"
				aria-haspopup="dialog"
				onClick={() => {
					setHour(hours);
					setMinute(minutes);
					setReady(false);
					setOpen(true);
				}}
			>
				<Clock3 size={17} aria-hidden />
				<span>Время по Минску</span>
				<strong>{value}</strong>
			</button>
			<Modal
				className="notification-time-modal"
				title="Время отправки"
				open={open}
				afterOpenChange={setReady}
				destroyOnHidden
				onCancel={() => setOpen(false)}
				footer={
					<Button
						type="primary"
						disabled={!ready}
						onClick={() => {
							onChange(twoDigits(hour) + ':' + twoDigits(minute));
							setOpen(false);
						}}
					>
						Выбрать время
					</Button>
				}
			>
				<div className="notification-wheel-grid">
					{open && (
						<>
							<TimeWheel
								label="Часы"
								count={24}
								initial={hours}
								current={hour}
								ready={ready}
								onChange={setHour}
							/>
							<TimeWheel
								label="Минуты"
								count={60}
								initial={minutes}
								current={minute}
								ready={ready}
								onChange={setMinute}
							/>
						</>
					)}
				</div>
			</Modal>
		</>
	);
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
		confirmSheet(modal, {
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
							filterOption={false}
							filterSort={sortSearchOptions}
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
				<div className="notification-field">
					<span id="notification-message-label">Текст сообщения</span>
					<Input.TextArea
						aria-labelledby="notification-message-label"
						value={config.text}
						maxLength={1500}
						autoSize={{ minRows: 3, maxRows: 8 }}
						onChange={(event) => update({ text: event.target.value })}
					/>
				</div>
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
				<button
					type="button"
					role="switch"
					aria-label="Автоматическая отправка"
					aria-checked={config.enabled}
					className="notification-schedule-switch"
					onClick={() => update({ enabled: !config.enabled })}
				>
					<span>
						<strong>Автоматическая отправка</strong>
						<small>{config.enabled ? 'Включена' : 'Выключена'}</small>
					</span>
					<span className="notification-switch-track" aria-hidden />
				</button>
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
					<ScheduleTime value={config.time} onChange={(time) => update({ time })} />
				</div>
				<Button
					type="primary"
					loading={busy}
					disabled={!valid || !config.weekdays.length}
					onClick={save}
				>
					Сохранить расписание
				</Button>
			</section>
			<DeliveryHistory deliveries={data.deliveries} />
		</div>
	);
}
