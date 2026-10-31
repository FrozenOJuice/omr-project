
# 
# Tiny script to update the generated SQLc code.
#

cd .\internal\database\sqlc
sqlc generate
cd ..\..\..\

cd .\internal\sys\sqlc
sqlc generate
cd ..\..\..\
