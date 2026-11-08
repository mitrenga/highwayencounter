SELECT `ndx`, `name`, `score`, `created`
FROM `rg_he_hallOfFame`
ORDER BY `ndx` DESC
LIMIT :limit
