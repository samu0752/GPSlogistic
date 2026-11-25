INSERT INTO events(user_id, created_at, action, details)
SELECT user_id, created_at, 'reversal',
       printf('Estorno #%d da operação #%d', id, reversal_of)
FROM operations WHERE kind='reversal' AND reversal_of IS NOT NULL ORDER BY id;

CREATE TRIGGER operation_audit_reversal AFTER INSERT ON operations
WHEN NEW.kind='reversal' AND NEW.reversal_of IS NOT NULL
BEGIN
    INSERT INTO events(user_id, created_at, action, details)
    VALUES (NEW.user_id, NEW.created_at, 'reversal',
            printf('Estorno #%d da operação #%d', NEW.id, NEW.reversal_of));
END;
