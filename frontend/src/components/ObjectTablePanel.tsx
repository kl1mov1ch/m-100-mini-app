import { Alert, App, Button, Input, Select, Upload } from 'antd';
import { Download, Trash2, Unlink } from 'lucide-react';
import { useState } from 'react';
import type { WorkspaceView } from '../App';
import { FieldHelp } from './FieldHelp';
import { BitrixReadStatus } from './BitrixReadStatus';
import { ObjectTableCard } from './ObjectTableCard';
import { downloadReport } from '../lib/report-download';

export function ObjectTablePanel({
	workspace,
	onDetach,
	onDelete,
	loadingAction,
}: {
	workspace: WorkspaceView;
	onDetach: () => void;
	onDelete: () => void;
	loadingAction: boolean;
}) {
	const [configuring, setConfiguring] = useState(false);
	const { message } = App.useApp();
	const {
		data,
		positions,
		url,
		setUrl,
		webhookId,
		setWebhookId,
		diskWebhooks,
		saveDiskWebhook,
		busy,
		upload,
		importRemote,
		resumeImport,
		retryJournal,
		openObjectSection,
	} = workspace;
	const config = data?.config;
	if (!config) return null;
	const connected = config.source === 'bitrix';
	const detached = config.source === 'detached';
	const ready = positions.length > 0 && !config.pending_import;
	const currentWebhookId = webhookId || config.webhook_profile_id || undefined;
	const saveCurrentWebhook = async () => {
		try {
			const saved = await saveDiskWebhook({ project_id: workspace.project });
			setWebhookId(saved.id);
			message.success('Вебхук сохранён в профиле');
		} catch (error) {
			message.error((error as Error).message);
		}
	};
	return (
		<section className="object-panel">
			<div className="object-panel-heading">
				<h2>Таблица</h2>
				{(connected || config.public_url || config.has_webhook) && (
					<Button danger icon={<Unlink size={16} />} onClick={onDetach}>
						Отвязать
					</Button>
				)}
			</div>
			{connected ? (
				<>
					<ObjectTableCard workspace={workspace} />
					<BitrixReadStatus workspace={workspace} />
					{config.has_webhook && config.file_id > 0 && config.journal_status !== 'ready' && (
						<Alert
							type="warning"
							showIcon
							message={config.journal_note || 'Проверьте запись листа «Журнал работ» в Битрикс24'}
							description={
								<Button size="small" loading={busy} onClick={retryJournal}>
									Повторить запись
								</Button>
							}
						/>
					)}
				</>
			) : (
				<>
					{detached && (
						<Alert
							type="warning"
							showIcon
							message="Таблица отвязана. Отчёты сохраняются в приложении."
						/>
					)}
					{ready ? (
						<p>
							<b>{config.source_name}</b> · {positions.length} работ
						</p>
					) : (
						<p>
							Подключите Битрикс24 или загрузите файл Excel. После чтения проверьте позиции сметы.
						</p>
					)}
				</>
			)}
			<div className="object-panel-actions">
				<Button
					type={!connected && !configuring ? 'primary' : 'default'}
					onClick={() => setConfiguring(!configuring)}
				>
					{configuring
						? 'Скрыть настройки'
						: connected
							? 'Настроить подключение'
							: 'Подключить Битрикс24'}
				</Button>
				{!connected && (
					<Upload accept=".xlsx,.csv" maxCount={1} showUploadList={false} beforeUpload={upload}>
						<Button loading={busy}>Загрузить Excel</Button>
					</Upload>
				)}
				{config.source === 'file' && ready && (
					<Button
						icon={<Download size={16} />}
						onClick={() =>
							void downloadReport('/imports/workbook.xlsx', workspace.project).catch(
								(error: Error) => message.error(error.message),
							)
						}
					>
						Скачать журнал
					</Button>
				)}
			</div>
			{configuring && (
				<div className="object-connection-form">
					<label>
						Ссылка на таблицу Битрикс24
						<Input
							value={url}
							onChange={(event) => setUrl(event.target.value)}
							placeholder="https://bitrix24public.com/…"
						/>
					</label>
					<label>
						Вебхук для записи <FieldHelp topic="bitrix" />
						<Select
							aria-label="Вебхук для записи"
							value={
								diskWebhooks.some(({ id }) => id === currentWebhookId)
									? currentWebhookId
									: undefined
							}
							onChange={setWebhookId}
							placeholder={config.has_webhook ? 'Текущий вебхук объекта' : 'Выберите из профиля'}
							options={diskWebhooks.map(({ id, name, portal }) => ({
								value: id,
								label: name === portal ? portal : name + ' · ' + portal,
							}))}
						/>
					</label>
					<div className="object-panel-actions">
						{config.has_webhook && !currentWebhookId && (
							<Button onClick={() => void saveCurrentWebhook()}>Сохранить текущий в профиль</Button>
						)}
						<Button type="text" onClick={() => workspace.setPage('more')}>
							Вебхуки в профиле
						</Button>
					</div>
					<Button
						type="primary"
						loading={busy}
						disabled={!url.trim() && !(config.file_id && (currentWebhookId || config.has_webhook))}
						onClick={importRemote}
					>
						Прочитать таблицу
					</Button>
				</div>
			)}
			{config.pending_import && (
				<Alert
					type="warning"
					showIcon
					message="Проверьте замечания и подтвердите импорт"
					description={
						<Button size="small" loading={busy} onClick={resumeImport}>
							Открыть проверку
						</Button>
					}
				/>
			)}
			{ready && (
				<Button type="primary" onClick={() => openObjectSection('catalogue')}>
					Проверить смету
				</Button>
			)}
			<div className="object-danger-zone">
				<Button
					type="text"
					danger
					icon={<Trash2 size={17} />}
					loading={loadingAction}
					onClick={onDelete}
				>
					Удалить объект
				</Button>
			</div>
		</section>
	);
}
