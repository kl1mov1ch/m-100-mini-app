import { Button, Tag } from 'antd';
import { ExternalLink, RefreshCw } from 'lucide-react';
import type { WorkspaceView } from '../App';
import dayjs from '../lib/date';
import { countLabel } from '../lib/format';
import { openExternalLink } from '../lib/telegram';

export function ObjectTableCard({ workspace }: { workspace: WorkspaceView }) {
	const {
		data,
		active,
		positions,
		checkingConnection,
		checkConnection,
		reviewBitrixChanges,
		busy,
	} = workspace;
	if (!data || !active || data.project?.id !== active.id || data.config.source !== 'bitrix')
		return null;
	const config = data.config;
	const check = config.connection_check;
	const original = config.detail_url || config.public_url;
	return (
		<section className="object-table-card">
			<div className="object-table-card-top">
				<div>
					<b>{config.source_name}</b>
					<small>{countLabel(positions.length, 'позиция', 'позиции', 'позиций')} · Битрикс24</small>
				</div>
				<Tag
					color={config.has_webhook ? 'green' : undefined}
					className={config.has_webhook ? undefined : 'status-tag-attention'}
				>
					{config.has_webhook ? 'Подключена' : 'Только чтение'}
				</Tag>
			</div>
			{(config.bitrix_read?.updated_at || config.last_import) && (
				<p className="table-updated-at">
					Обновлено{' '}
					{dayjs(config.bitrix_read?.updated_at || config.last_import).format('D MMMM, HH:mm')}
				</p>
			)}
			{config.bitrix_read?.status === 'unavailable' && (
				<p className="table-connection-notice" role="status">
					Битрикс24 недоступен. Показаны последние загруженные данные.
				</p>
			)}
			{config.bitrix_read?.status === 'review' && !check?.issues.length && (
				<Button
					type="text"
					className="table-review-link"
					loading={busy}
					onClick={reviewBitrixChanges}
				>
					Проверить различия с Битрикс24
				</Button>
			)}
			{check && (
				<div
					className={
						'table-check-result ' +
						(!check.reachable ? 'failed' : check.issues.length ? 'has-issues' : 'success')
					}
				>
					<b>{check.message}</b>
					{!check.issues.length && (
						<span>{dayjs(check.checked_at).format('D MMMM, HH:mm')} · Минск</span>
					)}
					{check.reachable && check.issues.length > 0 && (
						<>
							<span>
								{[
									check.issues[0].sheet,
									check.issues[0].affected_rows?.length
										? `столбец ${check.issues[0].column}`
										: check.issues[0].cell,
								]
									.filter(Boolean)
									.join(' · ')}
								{check.issues.length > 1 && ` · ещё ${check.issues.length - 1}`}
							</span>
							<Button size="small" onClick={reviewBitrixChanges} loading={busy}>
								Исправить
							</Button>
						</>
					)}
				</div>
			)}
			<div className="object-table-card-actions">
				<Button
					type="primary"
					aria-label="Проверить таблицу"
					loading={checkingConnection}
					disabled={busy}
					icon={<RefreshCw size={15} />}
					onClick={checkConnection}
				>
					Проверить
				</Button>
				{original && (
					<Button
						type="text"
						aria-label="Открыть таблицу Битрикс24"
						href={original}
						onClick={(event) => openExternalLink(event, original)}
						target="_blank"
						rel="noreferrer"
						icon={<ExternalLink size={15} />}
					>
						Открыть
					</Button>
				)}
			</div>
		</section>
	);
}
