import { Alert, Input, Modal } from 'antd';
import { TriangleAlert } from 'lucide-react';
import { useState, type ReactNode } from 'react';

export type ObjectAction = {
	title: string;
	label: string;
	description: ReactNode;
	confirmationName?: string;
	danger?: boolean;
	run: () => Promise<void>;
};

export function ObjectActionDialog({ action, close }: { action: ObjectAction; close: () => void }) {
	const [name, setName] = useState('');
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState('');
	const confirm = async () => {
		setSaving(true);
		setError('');
		try {
			await action.run();
			close();
		} catch (failure) {
			setError((failure as Error).message);
			setSaving(false);
		}
	};
	return (
		<Modal
			open
			title={action.title}
			okText={action.label}
			cancelText="Отмена"
			onCancel={() => !saving && close()}
			onOk={confirm}
			confirmLoading={saving}
			closable={!saving}
			maskClosable={false}
			cancelButtonProps={{ disabled: saving }}
			okButtonProps={{
				danger: action.danger,
				disabled: !!action.confirmationName && name.trim() !== action.confirmationName,
			}}
		>
			<div className="object-action-dialog">
				<Alert
					type="warning"
					showIcon
					icon={<TriangleAlert size={19} />}
					message={action.description}
				/>
				{action.confirmationName && (
					<label>
						Введите название объекта
						<Input
							value={name}
							onChange={(event) => setName(event.target.value)}
							disabled={saving}
						/>
					</label>
				)}
				{error && <Alert type="error" showIcon message={error} />}
			</div>
		</Modal>
	);
}
