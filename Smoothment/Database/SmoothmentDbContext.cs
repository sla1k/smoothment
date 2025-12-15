using Microsoft.EntityFrameworkCore;

namespace Smoothment.Database;

public class SmoothmentDbContext(DbContextOptions<SmoothmentDbContext> options)
    : DbContext(options)
{
    public DbSet<Payee> Payees { get; set; }
    public DbSet<Category> Categories { get; set; }


    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        modelBuilder.Entity<Category>()
            .Property(c => c.SynonymousJson)
            .HasColumnName("Synonymous");

        modelBuilder.Entity<Payee>()
            .Property(c => c.SynonymousJson)
            .HasColumnName("Synonymous");
    }
}
