using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace Smoothment.Database;

public class DesignTimeDbContextFactory : IDesignTimeDbContextFactory<SmoothmentDbContext>
{
    public SmoothmentDbContext CreateDbContext(string[] args)
    {
        var optionsBuilder = new DbContextOptionsBuilder<SmoothmentDbContext>();
        optionsBuilder.UseSqlite("Data Source=smoothment.db");

        return new SmoothmentDbContext(optionsBuilder.Options);
    }
}
