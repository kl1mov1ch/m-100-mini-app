import { Alert, App, Button, Input, Select, Switch, TimePicker, Tag, Empty } from 'antd';
import { Bell, Send } from 'lucide-react';
import { useEffect, useState } from 'react';
import dayjs from '../lib/date';
import { request } from '../lib/api';
import type { WorkspaceView } from '../App';

type ReminderConfig = { enabled: boolean; weekdays: number[]; time: string; text: string };
type ReminderData = {
	settings: ReminderConfig;
	recipients: { telegram_id: string; name: string; projects: string[] }[];
	deliveries: { name: string; day: string; status: string; error: string; created_at: string }[];
};

export function RemindersPage({ workspace }: { workspace: WorkspaceView }) {
	const { message, modal } = App.useApp();
	const [data, setData] = useState<ReminderData>();
	const [config, setConfig] = useState<ReminderConfig>();
	const [busy, setBusy] = useState(false);
	const testReminder = async () => {
		setBusy(true);
		try {
			const result = await request<{ sent: number; failed: number }>('/admin/reminders/test', {
				request_id: crypto.randomUUID(),
			});
			if (result.sent) message.success('Проверочное сообщение отправлено вам в Telegram');
			else message.warning('Сообщение не доставлено. Откройте бота и нажмите «Старт».');
			setData(await request<ReminderData>('/admin/reminders'));
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const load = async () => {
		const result = await request<ReminderData>('/admin/reminders');
		setData(result);
		setConfig(result.settings);
	};
	useEffect(() => {
		if (workspace.isAdmin) void load().catch((error) => message.error(error.message));
	}, []);
	if (!workspace.isAdmin) return null;
	const save = async () => {
		if (!config) return;
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
	const send = () =>
		modal.confirm({
			title: 'Отправить напоминания?',
			content: (
				<>
					<p>Сообщение получат только мастера без подтверждённого отчёта за сегодня.</p>
					<p>{config?.text}</p>
					<b>Получателей: {data?.recipients.length || 0}</b>
				</>
			),
			okText: 'Отправить',
			cancelText: 'Отмена',
			onOk: async () => {
				if (!config) return;
				await request('/admin/reminders/settings', config);
				const result = await request<{ sent: number; failed: number; skipped: number }>(
					'/admin/reminders/send',
					{ request_id: crypto.randomUUID() },
				);
				message.info(`Отправлено: ${result.sent}. Не доставлено: ${result.failed}.`);
				await load();
			},
		});
	return (
		<>
			<div className="page-title">
				<div>
					<span className="overline">АДМИНИСТРАТОР</span>
					<h1>Напоминания</h1>
				</div>
				<Bell size={24} />
			</div>
			{config && (
				<section className="settings-card reminder-settings">
					<div className="reminder-toggle">
						<div>
							<b>По расписанию</b>
							<small>Часовой пояс: Минск</small>
						</div>
						<Switch
							checked={config.enabled}
							onChange={(enabled) => setConfig({ ...config, enabled })}
						/>
					</div>
					<label>Дни недели</label>
					<Select
						mode="multiple"
						aria-label="Дни напоминаний"
						value={config.weekdays}
						onChange={(weekdays) => setConfig({ ...config, weekdays })}
						options={['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((label, value) => ({
							label,
							value,
						}))}
					/>
					<label>Время</label>
					<TimePicker
						aria-label="Время напоминания"
						format="HH:mm"
						minuteStep={5}
						allowClear={false}
						value={dayjs('2026-01-01T' + config.time)}
						onChange={(value) => value && setConfig({ ...config, time: value.format('HH:mm') })}
						inputReadOnly
					/>
					<label>Текст сообщения</label>
					<Input.TextArea
						value={config.text}
						onChange={(event) => setConfig({ ...config, text: event.target.value })}
						maxLength={1500}
						autoSize={{ minRows: 3, maxRows: 8 }}
					/>
					<Button
						type="primary"
						block
						onClick={save}
						loading={busy}
						disabled={!config.weekdays.length || !config.text.trim()}
					>
						Сохранить расписание
					</Button>
					<Button block onClick={testReminder} loading={busy}>
						Проверить уведомление себе
					</Button>
					<Alert
						type="info"
						showIcon
						message="Мастер должен открыть бота и нажать «Старт». Уведомление на телефоне зависит от настроек Telegram."
					/>
				</section>
			)}
			<section className="settings-card">
				<h2>
					Без отчёта сегодня{' '}
					<Tag className="status-tag-attention">{data?.recipients.length || 0}</Tag>
				</h2>
				<div className="reminder-recipients">
					{data?.recipients.map((recipient) => (
						<div key={recipient.telegram_id}>
							<b>{recipient.name}</b>
							<span>{recipient.projects.join(' · ')}</span>
						</div>
					))}
				</div>
				{!data?.recipients.length && (
					<Empty description="Нет мастеров без отчёта" image={Empty.PRESENTED_IMAGE_SIMPLE} />
				)}
				<Button
					block
					icon={<Send size={16} />}
					onClick={send}
					disabled={!data?.recipients.length || !config?.text.trim()}
				>
					Напомнить всем сейчас
				</Button>
			</section>
			<section className="settings-card">
				<h2>Последние отправки</h2>
				<div className="reminder-recipients">
					{data?.deliveries.map((item, index) => (
						<div key={item.created_at + index}>
							<b>
								{item.name}{' '}
								<Tag
									color={item.status === 'sent' ? 'green' : undefined}
									className={item.status === 'sent' ? undefined : 'status-tag-attention'}
								>
									{item.status === 'sent'
										? 'Отправлено'
										: item.status === 'sending'
											? 'Отправляется'
											: 'Не доставлено'}
								</Tag>
							</b>
							<span>
								{dayjs(item.created_at).format('D MMMM, HH:mm')}
								{item.error ? ' · ' + item.error : ''}
							</span>
						</div>
					))}
				</div>
				{!data?.deliveries.length && <p>Напоминаний пока не было</p>}
			</section>
		</>
	);
}
