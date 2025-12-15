using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Smoothment.Migrations
{
    /// <inheritdoc />
    public partial class Init : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "Categories",
                columns: table => new
                {
                    Name = table.Column<string>(type: "TEXT", nullable: false),
                    Synonymous = table.Column<string>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Categories", x => x.Name);
                });

            migrationBuilder.CreateTable(
                name: "Payees",
                columns: table => new
                {
                    Name = table.Column<string>(type: "TEXT", nullable: false),
                    ExpenseDescription = table.Column<string>(type: "TEXT", nullable: true),
                    ExpenseCategory = table.Column<string>(type: "TEXT", nullable: true),
                    TopUpDescription = table.Column<string>(type: "TEXT", nullable: true),
                    TopUpCategory = table.Column<string>(type: "TEXT", nullable: true),
                    Synonymous = table.Column<string>(type: "TEXT", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_Payees", x => x.Name);
                });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "Categories");

            migrationBuilder.DropTable(
                name: "Payees");
        }
    }
}
